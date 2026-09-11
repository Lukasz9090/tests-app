#!/usr/bin/env python3
"""Deterministic orchestration state for the multi-agent test pipeline.

The orchestrator LLM is a DISPATCHER, not a judge. It must never parse the
markdown artifacts itself nor decide "which round next" by reasoning. This
script derives the next action purely from the immutable, versioned artifacts
on disk (plans, generation reports, reviews) plus two numeric caps, and records
an audit ledger. The LLM runs it and executes the printed `next_action`.

Source of truth = the artifacts, not the ledger. Everything except the audit
trail is recomputed from files every call, so a lost ledger (git clean) never
corrupts control flow; `state` reconstructs it from the versioned artifacts.

stdlib-only; run with the plain `python` on PATH (`python3` where that is its
name). Same convention as every other script in this repo.

Subcommands
-----------
  state  <Slug> --repo . [--impl-cap 3] [--plan-cap 2]
      Print a JSON status block whose `next_action` is one of:
        PLAN | GENERATE | REVIEW | DONE | ESCALATE
      with the exact plan version / iteration to use and the artifact paths.

  ledger <Slug> --repo . [--event '<json>'] [--outcome DONE|ESCALATED]
      With --event: append one history entry (creates the ledger if missing).
      With --outcome: mark the run terminal. With neither: print the ledger.

Exit codes: 0 ok; 2 usage/IO error. `state` never fails on a missing pipeline —
"nothing yet" is a valid state (next_action = PLAN).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from md_payload import load_payload, save_payload  # noqa: E402

PLAN_STATUS_STOP = {"BLOCKED", "NEEDS_CLARIFICATION", "UNSUPPORTED_REPOSITORY"}
PLAN_STATUS_GO = {"READY", "READY_PARTIAL"}
# COMPLETE = valid plan, nothing left to implement. A success state, routed
# straight to DONE: dispatching a generator against it can only produce an
# empty report, which is both a wasted round and an artifact that violates
# generation-report.schema.json (results/minItems).
PLAN_STATUS_COMPLETE = "COMPLETE"
DECISION_ACCEPT = {"ACCEPT", "ACCEPT_PARTIAL"}
DECISION_STOP = {"NEEDS_TRIAGE", "BLOCKED"}


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def plan_dir(repo: Path, slug: str) -> Path:
    return repo / ".test-agent" / "plans" / slug


def _versions(directory: Path, pattern: re.Pattern) -> list[int]:
    if not directory.is_dir():
        return []
    found = set()
    for child in directory.iterdir():
        m = pattern.match(child.name)
        if m:
            found.add(int(m.group(1)))
    return sorted(found)


def gen_report_path(directory: Path, n: int, m: int) -> Path:
    # Iteration 1 is unsuffixed by generator convention; r2+ carry the suffix.
    name = f"generation-report-v{n}.md" if m == 1 else f"generation-report-v{n}-r{m}.md"
    return directory / name


def review_path(directory: Path, n: int, m: int) -> Path:
    return directory / f"review-v{n}-r{m}.md"


def _safe_payload(path: Path):
    try:
        payload, _ = load_payload(path)
        return payload
    except Exception as exc:  # malformed artifact must surface, not crash the loop
        return {"__error__": str(exc)}


def _gen_iterations(directory: Path, n: int) -> list[int]:
    iters = set()
    if (directory / f"generation-report-v{n}.md").is_file():
        iters.add(1)
    for k in _versions(directory, re.compile(rf"generation-report-v{n}-r(\d+)\.md$")):
        iters.add(k)
    return sorted(iters)


def _review_iterations(directory: Path, n: int) -> list[int]:
    return _versions(directory, re.compile(rf"review-v{n}-r(\d+)\.md$"))


def scenarios_in_scope(plan: dict) -> list[str]:
    """Ids the generator still has work on.

    Two independent axes live on a scenario: `change` (did the definition move?)
    and `implementation` (does a test exist?). Out of scope means COVERED — the
    test is written — or REMOVED — the behaviour is gone, so the test is a
    deletion candidate the human decides on, not generation work. Absent
    `implementation` means PENDING, which keeps plan-v1 (all NEW) in scope.
    """
    ids = []
    for scenario in plan.get("scenarios", []) or []:
        if not isinstance(scenario, dict):
            continue
        if scenario.get("implementation", "PENDING") == "COVERED":
            continue
        if scenario.get("change") == "REMOVED":
            continue
        ids.append(scenario.get("id"))
    return ids


def compute_state(repo: Path, slug: str, impl_cap: int, plan_cap: int) -> dict:
    directory = plan_dir(repo, slug)
    plan_versions = _versions(directory, re.compile(r"plan-v(\d+)\.md$"))

    out = {
        "target_slug": slug,
        "plan": {"version": None, "path": None, "status": None},
        "generation": {"iteration": None, "path": None},
        "review": {"iteration": None, "path": None, "decision": None,
                   "has_open_impl_feedback": False, "has_repeated_finding": False},
        "caps": {"impl_cap": impl_cap, "plan_cap": plan_cap},
        "next_action": None,
        "dispatch": None,
        "reason": None,
    }

    if not plan_versions:
        out["next_action"] = "PLAN"
        out["dispatch"] = {"agent": "test-planner", "plan_version": 1}
        out["reason"] = "no plan on disk; plan the target first"
        return out

    n = plan_versions[-1]
    p_path = directory / f"plan-v{n}.md"
    plan = _safe_payload(p_path)
    status = plan.get("status")
    out["plan"] = {"version": n, "path": str(p_path), "status": status}

    if "__error__" in plan:
        out["next_action"] = "ESCALATE"
        out["reason"] = f"plan-v{n}.md is unparseable: {plan['__error__']}"
        return out

    if status == PLAN_STATUS_COMPLETE:
        out["next_action"] = "DONE"
        out["reason"] = (f"plan v{n} is COMPLETE: every scenario is already implemented "
                         f"(implementation: COVERED) or REMOVED; nothing left to generate")
        return out

    if status in PLAN_STATUS_STOP:
        out["next_action"] = "ESCALATE"
        out["reason"] = f"planner returned status {status}; needs a human decision"
        return out

    if status not in PLAN_STATUS_GO:
        out["next_action"] = "ESCALATE"
        out["reason"] = f"unrecognized plan status {status!r}"
        return out

    in_scope = scenarios_in_scope(plan)
    out["plan"]["scenarios_in_scope"] = in_scope

    gen_iters = _gen_iterations(directory, n)
    rev_iters = _review_iterations(directory, n)
    gen_m = gen_iters[-1] if gen_iters else 0
    rev_m = rev_iters[-1] if rev_iters else 0

    if gen_m == 0:
        if not in_scope:
            # Belt and braces for a planner that wrote READY instead of COMPLETE:
            # with nothing PENDING there is no generation to dispatch, and an
            # empty generation report is not a valid artifact.
            out["next_action"] = "DONE"
            out["reason"] = (f"plan v{n} is {status} but no scenario is in scope "
                             f"(all COVERED or REMOVED); nothing to generate")
            return out
        out["next_action"] = "GENERATE"
        out["dispatch"] = {"agent": "test-generator", "plan_version": n, "iteration": 1,
                           "report_path": str(gen_report_path(directory, n, 1)),
                           "prior_review_path": None}
        out["reason"] = f"plan v{n} is {status} but has no generation yet"
        return out

    out["generation"] = {"iteration": gen_m, "path": str(gen_report_path(directory, n, gen_m))}

    if rev_m < gen_m:
        out["next_action"] = "REVIEW"
        out["dispatch"] = {"agent": "test-reviewer", "plan_version": n, "iteration": gen_m,
                           "review_path": str(review_path(directory, n, gen_m))}
        out["reason"] = f"generation iteration {gen_m} is awaiting review"
        return out

    # rev_m == gen_m: a review exists for the latest generation -> branch on decision
    r_path = review_path(directory, n, rev_m)
    review = _safe_payload(r_path)
    if "__error__" in review:
        out["next_action"] = "ESCALATE"
        out["review"] = {"iteration": rev_m, "path": str(r_path), "decision": None,
                         "has_open_impl_feedback": False, "has_repeated_finding": False}
        out["reason"] = f"{r_path.name} is unparseable: {review['__error__']}"
        return out

    decision = review.get("decision")
    findings = review.get("findings", []) or []
    repeated = any(bool(f.get("repeated")) for f in findings)
    impl_feedback = (review.get("feedback", {}) or {}).get("implementation", []) or []
    out["review"] = {
        "iteration": rev_m, "path": str(r_path), "decision": decision,
        "has_open_impl_feedback": bool(impl_feedback),
        "has_repeated_finding": repeated,
    }

    if decision in DECISION_ACCEPT:
        out["next_action"] = "DONE"
        out["reason"] = f"reviewer decided {decision} at v{n}-r{rev_m}"
        return out

    if decision in DECISION_STOP:
        out["next_action"] = "ESCALATE"
        out["reason"] = f"reviewer decided {decision}; belongs to a human (spec/code or unrunnable check)"
        return out

    if decision == "REPAIR_IMPLEMENTATION":
        if gen_m >= impl_cap:
            out["next_action"] = "ESCALATE"
            out["reason"] = f"REPAIR_IMPLEMENTATION but impl_cap {impl_cap} reached at v{n} (rounds={gen_m})"
            return out
        out["next_action"] = "GENERATE"
        out["dispatch"] = {
            "agent": "test-generator", "plan_version": n, "iteration": gen_m + 1,
            "report_path": str(gen_report_path(directory, n, gen_m + 1)),
            "prior_review_path": str(r_path),  # carries feedback.implementation forward
        }
        out["reason"] = f"reviewer asked to repair implementation; round {gen_m + 1} of {impl_cap}"
        return out

    if decision == "REPAIR_PLAN":
        if n >= plan_cap:
            out["next_action"] = "ESCALATE"
            out["reason"] = f"REPAIR_PLAN but plan_cap {plan_cap} reached (plan versions={n})"
            return out
        out["next_action"] = "PLAN"
        out["dispatch"] = {
            "agent": "test-planner", "plan_version": n + 1, "based_on_version": n,
            # CRITICAL: implementation findings must survive the plan bump, or a
            # weak-assertion finding from v{n} silently dies when the generator
            # later looks only for a review of v{n+1} (which won't exist yet).
            "carry_review_path": str(r_path) if impl_feedback else None,
            # The planner classifies `implementation` from these, not from a
            # grep of the test files — see test-planner Phase 2.5.
            "prior_generation_report_path": str(gen_report_path(directory, n, gen_m)),
            "prior_review_path": str(r_path),
        }
        out["reason"] = f"reviewer asked to repair the plan; writing plan v{n + 1}"
        return out

    out["next_action"] = "ESCALATE"
    out["reason"] = f"unrecognized review decision {decision!r}"
    return out


def ledger_file(repo: Path, slug: str) -> Path:
    return plan_dir(repo, slug) / "run-ledger.md"


def _empty_ledger(slug: str) -> dict:
    return {
        "schema_version": 1,
        "target_slug": slug,
        "created": _now(),
        "updated": _now(),
        "status": "RUNNING",
        "history": [],
        "outcome": None,
    }


def ledger_read(repo: Path, slug: str) -> dict | None:
    path = ledger_file(repo, slug)
    if not path.is_file():
        return None
    payload, _ = load_payload(path)
    return payload


def ledger_write(repo: Path, slug: str, payload: dict) -> None:
    path = ledger_file(repo, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated"] = _now()
    title = f"# Orchestration Ledger: {slug}\n"
    summary = (f"Run {payload.get('status', '?')}; {len(payload.get('history', []))} step(s) recorded. "
               f"This file is an audit trail — control flow is recomputed from the versioned "
               f"artifacts by `orchestrate.py state`, never from here.\n\n")
    if path.is_file():
        _, original = load_payload(path)
        save_payload(path, payload, original)
    else:
        body = title + summary + "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```\n"
        path.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("state")
    s.add_argument("slug")
    s.add_argument("--repo", default=".")
    s.add_argument("--impl-cap", type=int, default=3)
    s.add_argument("--plan-cap", type=int, default=2)

    l = sub.add_parser("ledger")
    l.add_argument("slug")
    l.add_argument("--repo", default=".")
    l.add_argument("--event", default=None, help="JSON object to append to history")
    l.add_argument("--outcome", default=None, choices=["DONE", "ESCALATED"])

    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    if args.cmd == "state":
        state = compute_state(repo, args.slug, args.impl_cap, args.plan_cap)
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "ledger":
        payload = ledger_read(repo, args.slug) or _empty_ledger(args.slug)
        if args.event:
            try:
                entry = json.loads(args.event)
            except json.JSONDecodeError as exc:
                print(f"--event is not valid JSON: {exc}", file=sys.stderr)
                return 2
            entry.setdefault("ts", _now())
            payload["history"].append(entry)
        if args.outcome:
            payload["status"] = args.outcome
            payload["outcome"] = args.outcome
        ledger_write(repo, args.slug, payload)
        if not args.event and not args.outcome:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"ledger updated: {ledger_file(repo, args.slug)}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())