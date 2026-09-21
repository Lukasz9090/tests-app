#!/usr/bin/env python3
"""Run lifecycle and in-run control flow for the test pipeline (Model B).

The orchestrator LLM is a DISPATCHER, not a judge. It never parses an artifact
and never decides "what next" by reasoning: it runs this script and does the
printed `next_action`.

Two kinds of state, never mixed:

  * BETWEEN runs there is no stored state. `start` derives the truth from the
    code, the tests, git, coverage and mutations (tc_derive_state.py).
  * INSIDE a run the plan -> generate -> review loop is driven by the artifacts
    of THAT run only, in `.test-agent/runs/<slug>/<run-id>/`. No script ever
    reads another run's directory; old runs stay on disk for people to read.

Subcommands
-----------
  start  <slug> --repo . --mode legacy|spec-driven [--interactive] [--spec P]
                [--impl-cap 3] [--plan-cap 2] [--commit]
      Create the run directory and run.json (the ONLY place mode, interactive,
      spec, caps and commit are given), then run derive-state. Prints run_id.

  state  <slug> --repo . --run <id|latest>
      Print the in-run `next_action`: PLAN | GENERATE | REVIEW | RESEAL | FINISH,
      with `dispatch` (who to call, which files) and, on FINISH, the outcome.

  reseal <slug> --repo . --run <id|latest>
      Move the freeze point of stale-but-green characterization tests to the
      current sha. Touches only the `tc-agent-characterizes` line of those methods.

  finish <slug> --repo . --run <id|latest>
      Write run-report.md and print it. With `commit: true` in run.json, commit
      the run's test files (only on DONE / DONE_PARTIAL; never on a protected
      branch - a new `tc-agent/<slug>/<run-id>` branch is created instead).

Exit codes: 0 ok; 2 usage / IO error / the run is not in a state to do that.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_common as c  # noqa: E402
import tc_derive_state as ds  # noqa: E402
import tc_git as g  # noqa: E402
import tc_javadoc as j  # noqa: E402
from tc_md_payload import load_payload  # noqa: E402

MODES = ("legacy", "spec-driven")
PLAN_STOP = {"BLOCKED": "BLOCKED", "NEEDS_CLARIFICATION": "ESCALATED",
             "UNSUPPORTED_REPOSITORY": "ESCALATED"}
PLAN_GO = {"READY", "READY_PARTIAL"}
DERIVE_TERMINAL = {"RED": "RED", "BLOCKED": "BLOCKED", "ESCALATE": "ESCALATED"}
COMMIT_OUTCOMES = {"DONE", "DONE_PARTIAL"}


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def rel(path: Path, repo: Path) -> str:
    """Repo-relative, forward slashes: agents paste these into prompts."""
    try:
        return Path(path).resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _safe(path: Path):
    try:
        return load_payload(path)[0]
    except Exception as exc:  # a malformed artifact must surface, not crash the loop
        return {"__error__": str(exc)}


# -------------------------------------------------------- run artifacts ---


def _numbers(directory: Path, pattern: str) -> list:
    rx = re.compile(pattern)
    found = set()
    if directory.is_dir():
        for child in directory.iterdir():
            m = rx.match(child.name)
            if m:
                found.add(int(m.group(1)))
    return sorted(found)


def plan_versions(d: Path) -> list:
    return _numbers(d, r"plan-v(\d+)\.md$")


def plan_path(d: Path, n: int) -> Path:
    return d / f"plan-v{n}.md"


def gen_path(d: Path, n: int, m: int) -> Path:
    return d / (f"generation-report-v{n}.md" if m == 1 else f"generation-report-v{n}-r{m}.md")


def gen_iterations(d: Path, n: int) -> list:
    found = set(_numbers(d, rf"generation-report-v{n}-r(\d+)\.md$"))
    if (d / f"generation-report-v{n}.md").is_file():
        found.add(1)
    return sorted(found)


def review_path(d: Path, n: int, m: int) -> Path:
    return d / f"review-v{n}-r{m}.md"


def review_iterations(d: Path, n: int) -> list:
    return _numbers(d, rf"review-v{n}-r(\d+)\.md$")


def newest_review(d: Path) -> Path | None:
    for n in reversed(plan_versions(d)):
        its = review_iterations(d, n)
        if its:
            return review_path(d, n, its[-1])
    return None


def all_reports(d: Path) -> list:
    out = []
    for n in plan_versions(d):
        for m in gen_iterations(d, n):
            out.append(gen_path(d, n, m))
    return out


# ------------------------------------------------------------------ start ---


def new_run_id(root: Path) -> str:
    base = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id, k = base, 2
    while (root / run_id).exists():
        run_id, k = f"{base}-{k}", k + 1
    return run_id


def cmd_start(args) -> int:
    repo = Path(args.repo).resolve()
    if args.mode not in MODES:
        print(f"--mode must be one of {', '.join(MODES)} (tdd is reserved, not implemented)",
              file=sys.stderr)
        return 2
    if args.spec and not (repo / args.spec).is_file() and not Path(args.spec).is_file():
        print(f"--spec {args.spec}: file not found", file=sys.stderr)
        return 2
    root = c.runs_root(repo, args.slug)
    run_id = new_run_id(root)
    directory = root / run_id
    directory.mkdir(parents=True)
    run = {
        "schema_version": 1,
        "slug": args.slug,
        "run_id": run_id,
        "mode": args.mode,
        "interactive": bool(args.interactive),
        "spec": args.spec,
        "caps": {"impl_cap": args.impl_cap, "plan_cap": args.plan_cap},
        "commit": bool(args.commit),
        "started": _now(),
        "resealed": False,
    }
    c.save_run(directory, run)
    state = ds.derive(repo, args.slug, run)
    ds.write(directory, state)
    print(json.dumps({
        "run_id": run_id,
        "run_dir": rel(directory, repo),
        "derive_state": {"next_action": state["next_action"], "reasons": state["reasons"],
                         "detail": state.get("detail")},
        "next": f"python .github/agents/tc-agent/scripts/tc_orchestrate.py state {args.slug} "
                f"--repo . --run {run_id}",
    }, indent=2, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ state ---


def compute_state(repo: Path, directory: Path) -> dict:
    run = c.load_run(directory)
    caps = run.get("caps", {})
    impl_cap, plan_cap = int(caps.get("impl_cap", 3)), int(caps.get("plan_cap", 2))
    out = {
        "slug": run["slug"],
        "run_id": run["run_id"],
        "run_dir": rel(directory, repo),
        "next_action": None,
        "outcome": None,
        "reason": None,
        "dispatch": None,
        "derive": None,
    }

    def finish(outcome: str, reason: str) -> dict:
        out["next_action"], out["outcome"], out["reason"] = "FINISH", outcome, reason
        out["dispatch"] = {"command": f"tc_orchestrate.py finish {run['slug']} --repo . "
                                      f"--run {run['run_id']}"}
        return out

    derive = _safe(directory / "derive-state.md")
    if "__error__" in derive:
        return finish("ESCALATED", f"derive-state.md is unreadable: {derive['__error__']}")
    d_action = derive.get("next_action")
    out["derive"] = {"next_action": d_action, "reasons": derive.get("reasons", [])}

    if d_action in DERIVE_TERMINAL:
        return finish(DERIVE_TERMINAL[d_action],
                      f"derive-state: {d_action} ({', '.join(derive.get('reasons', []))})"
                      + (f" - {derive['detail']}" if derive.get("detail") else ""))

    if derive.get("reseal") and not run.get("resealed"):
        out["next_action"] = "RESEAL"
        out["reason"] = f"{len(derive['reseal'])} stale characterization test(s) still pass"
        out["dispatch"] = {"command": f"tc_orchestrate.py reseal {run['slug']} --repo . "
                                      f"--run {run['run_id']}"}
        return out

    if d_action == "DONE":
        return finish("DONE", "derive-state: gates met on the current code, nothing stale is red")

    if d_action != "PLAN":
        return finish("ESCALATED", f"unrecognized derive-state next_action {d_action!r}")

    versions = plan_versions(directory)
    if not versions:
        out["next_action"] = "PLAN"
        out["reason"] = f"derive-state: {', '.join(derive.get('reasons', []))}"
        out["dispatch"] = {"agent": "tc-planner", "run_dir": out["run_dir"],
                           "plan_path": rel(plan_path(directory, 1), repo),
                           "review_path": None}
        return out

    n = versions[-1]
    plan = _safe(plan_path(directory, n))
    if "__error__" in plan:
        return finish("ESCALATED", f"plan-v{n}.md is unparseable: {plan['__error__']}")
    status = plan.get("status")
    if status in PLAN_STOP:
        return finish(PLAN_STOP[status], f"planner returned {status}"
                      + (f": {plan.get('reason')}" if plan.get("reason") else ""))
    if status == "COMPLETE":
        return finish("DONE", f"plan v{n} is COMPLETE: nothing left to generate")
    if status not in PLAN_GO:
        return finish("ESCALATED", f"unrecognized plan status {status!r}")

    gens = gen_iterations(directory, n)
    revs = review_iterations(directory, n)
    gen_m = gens[-1] if gens else 0
    rev_m = revs[-1] if revs else 0
    latest_review = newest_review(directory)

    if gen_m == 0:
        out["next_action"] = "GENERATE"
        out["reason"] = f"plan v{n} is {status} and has no generation yet"
        out["dispatch"] = {"agent": "tc-generator", "run_dir": out["run_dir"],
                           "plan_path": rel(plan_path(directory, n), repo),
                           "report_path": rel(gen_path(directory, n, 1), repo),
                           "review_path": rel(latest_review, repo) if latest_review else None}
        return out

    if rev_m < gen_m:
        out["next_action"] = "REVIEW"
        out["reason"] = f"generation v{n}-r{gen_m} awaits review"
        out["dispatch"] = {"agent": "tc-reviewer", "run_dir": out["run_dir"],
                           "plan_path": rel(plan_path(directory, n), repo),
                           "report_path": rel(gen_path(directory, n, gen_m), repo),
                           "previous_review_path": rel(latest_review, repo) if latest_review else None,
                           "review_path": rel(review_path(directory, n, gen_m), repo),
                           "label": f"v{n}-r{gen_m}"}
        return out

    r_path = review_path(directory, n, rev_m)
    review = _safe(r_path)
    if "__error__" in review:
        return finish("ESCALATED", f"{r_path.name} is unparseable: {review['__error__']}")
    decision = review.get("decision")
    if decision == "ACCEPT":
        return finish("DONE", f"reviewer decided ACCEPT at v{n}-r{rev_m}")
    if decision == "ACCEPT_PARTIAL":
        return finish("DONE_PARTIAL", f"reviewer decided ACCEPT_PARTIAL at v{n}-r{rev_m}")
    if decision in ("NEEDS_TRIAGE", "BLOCKED"):
        return finish("ESCALATED", f"reviewer decided {decision} at v{n}-r{rev_m}; a human decides")
    if decision == "REPAIR_IMPLEMENTATION":
        if gen_m >= impl_cap:
            return finish("ESCALATED", f"REPAIR_IMPLEMENTATION but impl_cap {impl_cap} reached "
                                       f"at v{n} (rounds={gen_m})")
        out["next_action"] = "GENERATE"
        out["reason"] = f"reviewer asked to repair the implementation; round {gen_m + 1} of {impl_cap}"
        out["dispatch"] = {"agent": "tc-generator", "run_dir": out["run_dir"],
                           "plan_path": rel(plan_path(directory, n), repo),
                           "report_path": rel(gen_path(directory, n, gen_m + 1), repo),
                           "review_path": rel(r_path, repo)}
        return out
    if decision == "REPAIR_PLAN":
        if n >= plan_cap:
            return finish("ESCALATED", f"REPAIR_PLAN but plan_cap {plan_cap} reached (plan versions={n})")
        out["next_action"] = "PLAN"
        out["reason"] = f"reviewer asked to repair the plan; writing plan v{n + 1}"
        out["dispatch"] = {"agent": "tc-planner", "run_dir": out["run_dir"],
                           "plan_path": rel(plan_path(directory, n + 1), repo),
                           "review_path": rel(r_path, repo)}
        return out
    return finish("ESCALATED", f"unrecognized review decision {decision!r}")


def cmd_state(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        directory = c.run_dir(repo, args.slug, args.run)
    except c.CheckError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(compute_state(repo, directory), indent=2, ensure_ascii=False))
    return 0


# ----------------------------------------------------------------- reseal ---


def do_reseal(repo: Path, directory: Path) -> dict:
    run = c.load_run(directory)
    derive = _safe(directory / "derive-state.md")
    if "__error__" in derive:
        raise c.CheckError(f"derive-state.md is unreadable: {derive['__error__']}")
    if run.get("resealed"):
        return {"resealed": run.get("resealed_methods", []), "note": "already resealed in this run"}
    if (derive.get("git") or {}).get("dirty"):
        raise c.CheckError("the target is dirty; there is no sha to reseal to")
    target_class = (derive.get("target") or {}).get("class")
    done = []
    for item in derive.get("reseal", []) or []:
        changed, detail = j.reseal(repo / item["file"], item["method"], target_class, item["to"])
        done.append({**item, "changed": changed, "detail": detail})
    run["resealed"] = True
    run["resealed_methods"] = done
    c.save_run(directory, run)
    return {"resealed": done}


def cmd_reseal(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        directory = c.run_dir(repo, args.slug, args.run)
        result = do_reseal(repo, directory)
    except c.CheckError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


# ----------------------------------------------------------------- finish ---


def _pct(value) -> str:
    return f"{value:.0%}" if isinstance(value, (int, float)) else "?"


def collect(repo: Path, directory: Path, state: dict) -> dict:
    """Everything the report and the commit need, read from THIS run only."""
    run = c.load_run(directory)
    derive = _safe(directory / "derive-state.md")
    versions = plan_versions(directory)
    plan = _safe(plan_path(directory, versions[-1])) if versions else {}
    r_path = newest_review(directory)
    review = _safe(r_path) if r_path else {}

    results, test_files, suggestions = {}, [], []
    for report_path in all_reports(directory):
        report = _safe(report_path)
        if "__error__" in report:
            continue
        for f in report.get("test_files", []) or []:
            if f not in test_files:
                test_files.append(f)
        for r in report.get("results", []) or []:
            results[r.get("test_method") or r.get("id")] = r
        for s in report.get("suggestions", []) or []:
            if s.get("suggestion") not in [x.get("suggestion") for x in suggestions]:
                suggestions.append(s)

    written = [k for k, r in results.items() if r.get("status") == "IMPLEMENTED"]
    placeholders_written = [k for k, r in results.items() if r.get("status") == "PLACEHOLDER"]
    resealed = [x for x in run.get("resealed_methods", []) if x.get("changed")]
    for x in resealed:
        if x["file"] not in test_files:
            test_files.append(x["file"])

    # Placeholders now in the code decide DONE vs DONE_PARTIAL.
    placeholders_in_code = []
    try:
        target = c.resolve_target(repo, run["slug"])
        placeholders_in_code = [m.key for m in ds.tier1(repo, target)["placeholders"]]
    except c.CheckError:
        target = None

    # The newest test check of the run tells whether the tree is left red.
    red = {}
    checks = sorted((directory / "checks").glob("tests-*.md"), key=lambda p: p.stat().st_mtime) \
        if (directory / "checks").is_dir() else []
    if checks:
        last = _safe(checks[-1])
        if last.get("status") == "COMPILE_ERROR":
            red = {"report": rel(checks[-1], repo), "compile_errors": last.get("compiler_errors", [])[:10]}
        elif last.get("failures"):
            red = {"report": rel(checks[-1], repo),
                   "failures": [{"test": f.get("test"), "location": f.get("location"),
                                 "failure_phase": f.get("failure_phase"),
                                 "message": (f.get("message") or "")[:200]}
                                for f in last["failures"][:10]]}

    gates = {}
    rchecks = (review.get("checks") or {}) if "__error__" not in review else {}
    cov = rchecks.get("coverage") or derive.get("coverage") or {}
    mut = rchecks.get("mutation") or derive.get("mutation") or {}
    if cov.get("branch_ratio") is not None:
        gates["coverage"] = {"ratio": cov.get("branch_ratio"), "gate": cov.get("gate")}
    if mut.get("score") is not None:
        gates["mutation"] = {"ratio": mut.get("score"), "gate": mut.get("gate")}

    notes = ((plan.get("context") or {}).get("notes") or []) if "__error__" not in plan else []
    return {
        "run": run,
        "derive": derive,
        "plan": plan,
        "plan_status": plan.get("status"),
        "review": review if "__error__" not in review else {},
        "review_path": rel(r_path, repo) if r_path else None,
        "target_class": (derive.get("target") or {}).get("class") or run["slug"].split(".")[0],
        "sha": (derive.get("git") or {}).get("current_sha"),
        "written": written,
        "placeholders_written": placeholders_written,
        "placeholders_in_code": placeholders_in_code,
        "resealed": resealed,
        "test_files": test_files,
        "suggestions": suggestions,
        "unimplementable": (review.get("unimplementable") or []) if "__error__" not in review else [],
        "obsolete": (plan.get("obsolete") or []) if "__error__" not in plan else [],
        "confirm": [n for n in notes if str(n).startswith("CONFIRM:")],
        "red": red,
        "gates": gates,
    }


def template_summary(info: dict, outcome: str) -> str:
    cls, sha = info["target_class"], info["sha"] or "?"
    parts = []
    if info["resealed"]:
        parts.append(f"Resealed {len(info['resealed'])} characterization test(s) of {cls} to {sha}; "
                     f"they still pass, so the behaviour they froze did not change.")
    if info["plan_status"] == "COMPLETE":
        k = len(info["placeholders_in_code"])
        parts.append(f"No new tests were generated for {cls}: the planner found the remaining "
                     f"coverage gap fully explained by {k} deliberate @Disabled placeholder(s)."
                     if k else f"No new tests were generated for {cls}: nothing was left to plan.")
    if outcome in COMMIT_OUTCOMES and not parts:
        parts.append(f"No changes were needed: the tests for {cls} pass and the coverage and "
                     f"mutation gates are met on {sha}.")
    if outcome not in COMMIT_OUTCOMES:
        parts.append(f"The run for {cls} ended {outcome}; see the run report for what a human "
                     f"has to decide.")
    return " ".join(parts)


def commit_message(info: dict, outcome: str, summary: str, report_rel: str) -> str:
    run = info["run"]
    lines = [f"test({run['slug']}): tc-agent {outcome} [run {run['run_id']}]", ""]
    lines += textwrap.wrap(summary, 72) or ["(no summary)"]
    lines.append("")
    mode = run["mode"] + (" (interactive)" if run.get("interactive") else "")
    lines.append(f"Mode: {mode} | target: {info['target_class']}@{info['sha'] or '?'}")
    lines.append(f"Tests: +{len(info['written'])} written, {len(info['placeholders_written'])} "
                 f"placeholders, {len(info['resealed'])} resealed")
    gate_parts = []
    if "coverage" in info["gates"]:
        gc = info["gates"]["coverage"]
        gate_parts.append(f"branch coverage {_pct(gc['ratio'])} (gate {_pct(gc['gate'])})")
    if "mutation" in info["gates"]:
        gm = info["gates"]["mutation"]
        gate_parts.append(f"mutation {_pct(gm['ratio'])} (gate {_pct(gm['gate'])})")
    if gate_parts:
        lines.append("Gates: " + ", ".join(gate_parts))
    if info["suggestions"]:
        lines.append("Suggestions: " + "; ".join(s.get("suggestion", "") for s in info["suggestions"][:3]))
    lines.append(f"Report: {report_rel}")
    return "\n".join(lines) + "\n"


def is_protected(branch: str | None, patterns: list) -> bool:
    if branch is None:              # detached HEAD, typical on CI
        return True
    return any(fnmatch.fnmatchcase(branch, p) for p in patterns)


def do_commit(repo: Path, directory: Path, info: dict, outcome: str, message: str) -> dict:
    run = info["run"]
    if outcome not in COMMIT_OUTCOMES:
        return {"status": "skipped", "reason": f"outcome {outcome}: only DONE / DONE_PARTIAL commit"}
    files = []
    for f in info["test_files"]:
        p = Path(f)
        if p.is_absolute() or ".." in p.parts or "src/main" in p.as_posix() \
                or ".test-agent" in p.parts or not (repo / p).exists():
            continue
        if g.changed(repo, repo / p):
            files.append(p.as_posix())
    if not files:
        return {"status": "skipped", "reason": "nothing to commit: no test file of this run changed"}
    already = g.staged_files(repo)
    if already:
        return {"status": "skipped", "reason": "index not clean: files are already staged "
                                               f"({', '.join(already[:5])})"}
    patterns, source = c.protected_branches(repo)
    branch = g.current_branch(repo)
    created = None
    if is_protected(branch, patterns):
        created = f"tc-agent/{run['slug']}/{run['run_id']}"
        if g.branch_exists(repo, created):
            return {"status": "skipped", "reason": f"branch {created} already exists"}
        code, output = g.git(repo, "switch", "-c", created)
        if code != 0:
            code, output = g.git(repo, "checkout", "-b", created)
        if code != 0:
            return {"status": "failed", "reason": f"cannot create branch {created}: {output[-300:]}"}
    code, output = g.git(repo, "add", "--", *files)
    if code != 0:
        return {"status": "failed", "reason": f"git add failed: {output[-300:]}", "branch": created or branch}
    msg_file = directory / "commit-message.txt"
    msg_file.write_text(message, encoding="utf-8")
    code, output = g.git(repo, "commit", "-F", str(msg_file))
    if code != 0:
        g.git(repo, "reset", "-q", "--", *files)
        return {"status": "failed", "reason": f"git commit failed: {output[-300:]}",
                "branch": created or branch}
    return {
        "status": "committed",
        "sha": g.head_sha(repo),
        "branch": created or branch,
        "created_branch": created is not None,
        "from_branch": branch if created else None,
        "protected_from": source,
        "files": files,
    }


def render_report(info: dict, state: dict, outcome: str, summary: str, commit: dict | None,
                  report_rel: str) -> tuple[str, dict]:
    run = info["run"]
    lines = [f"# Run report: {run['slug']} ({run['run_id']})", ""]
    if info["red"]:
        lines.append("**THE WORKING TREE IS RED - the build is broken until someone acts.**")
        for f in info["red"].get("failures", []):
            lines.append(f"- FAILING {f['test']} at {f.get('location') or '?'} "
                         f"({f.get('failure_phase')}): {f.get('message')}")
        for e in info["red"].get("compile_errors", []):
            lines.append(f"- COMPILE ERROR {e}")
        lines.append("Your choice: fix the production code, repair the test by hand, or delete it.")
        lines.append("")
    lines.append(f"**Outcome: {outcome}** — {state.get('reason')}")
    lines.append("")
    lines.append(summary)
    lines.append("")
    lines.append(f"- mode: {run['mode']}{' (interactive)' if run.get('interactive') else ''}; "
                 f"target {info['target_class']}@{info['sha'] or '?'}")
    lines.append(f"- tests written: {len(info['written'])}; placeholders written: "
                 f"{len(info['placeholders_written'])}; resealed: {len(info['resealed'])}; "
                 f"placeholders now in the code: {len(info['placeholders_in_code'])}")
    if info["test_files"]:
        lines.append(f"- files changed in the working tree: {', '.join(info['test_files'])}")
    if info["gates"]:
        g_ = info["gates"]
        parts = []
        if "coverage" in g_:
            parts.append(f"branch coverage {_pct(g_['coverage']['ratio'])} (gate {_pct(g_['coverage']['gate'])})")
        if "mutation" in g_:
            parts.append(f"mutation {_pct(g_['mutation']['ratio'])} (gate {_pct(g_['mutation']['gate'])})")
        lines.append("- gates: " + ", ".join(parts))
    for u in info["unimplementable"]:
        lines.append(f"- unimplementable {u.get('id')}: {u.get('reason')}"
                     + (f" -> {u['suggestion']}" if u.get("suggestion") else ""))
    for s in info["suggestions"]:
        lines.append(f"- suggestion (recommend, never applied): {s.get('suggestion')} — {s.get('rationale')}")
    for o in info["obsolete"]:
        lines.append(f"- obsolete test (deletion candidate, not deleted): {o.get('test')} — {o.get('reason')}")
    for q in info["confirm"]:
        lines.append(f"- {q}")
    defects = ((info["derive"].get("tests") or {}).get("metadata_defects") or [])
    for d in defects[:10]:
        lines.append(f"- metadata defect: {d}")

    steps = []
    reasons = (info["derive"].get("reasons") or [])
    if "TARGET_TOO_FRESH" in reasons:
        steps.append("the target's last commit is too recent for legacy mode: re-run with "
                     "--interactive, or in spec-driven mode, or wait until it has been validated")
    if "TARGET_DIRTY" in reasons or "TARGET_NOT_COMMITTED" in reasons:
        steps.append("commit the change to the target first, then re-run")
    if commit and commit.get("status") == "committed":
        where = commit["branch"]
        if commit.get("created_branch"):
            origin = commit.get("from_branch") or "a detached HEAD"
            steps.append(f"{origin} is protected, so the commit {commit['sha']} went to a NEW branch "
                         f"{where} (now checked out); {origin} is unchanged. Push it and open a merge "
                         f"request when ready. Any other uncommitted changes moved with the checkout.")
        else:
            steps.append(f"committed {commit['sha']} on {where}; push when ready")
    elif info["test_files"] and outcome in COMMIT_OUTCOMES:
        steps.append(f"review and commit: {', '.join(info['test_files'])}")
    if commit and commit.get("status") in ("skipped", "failed") and run.get("commit"):
        steps.append(f"commit {commit['status']}: {commit['reason']}")
    if steps:
        lines.append("")
        lines.append("**Next steps**")
        lines += [f"- {s}" for s in steps]
    data = {
        "schema_version": 1,
        "slug": run["slug"],
        "run_id": run["run_id"],
        "outcome": outcome,
        "reason": state.get("reason"),
        "summary": summary,
        "target": f"{info['target_class']}@{info['sha']}",
        "written": info["written"],
        "placeholders_written": info["placeholders_written"],
        "placeholders_in_code": info["placeholders_in_code"],
        "resealed": [x["method"] for x in info["resealed"]],
        "test_files": info["test_files"],
        "red": info["red"],
        "gates": info["gates"],
        "unimplementable": info["unimplementable"],
        "suggestions": info["suggestions"],
        "obsolete": info["obsolete"],
        "confirm": info["confirm"],
        "commit": commit,
        "next_steps": steps,
        "report": report_rel,
    }
    return "\n".join(lines) + "\n", data


def do_finish(repo: Path, directory: Path) -> tuple[int, str]:
    run = c.load_run(directory)
    report = directory / "run-report.md"
    if run.get("finished") and report.is_file():
        text = report.read_text(encoding="utf-8")
        return 0, text.split("```json")[0].rstrip() + "\n\n(already finished)\n"
    state = compute_state(repo, directory)
    if state["next_action"] != "FINISH":
        return 2, (f"the run is not finished: next_action is {state['next_action']} "
                   f"({state.get('reason')}). Do that first.")
    info = collect(repo, directory, state)
    outcome = state["outcome"]
    if outcome == "DONE" and info["placeholders_in_code"]:
        outcome = "DONE_PARTIAL"
    review_summary = (info["review"].get("commit_summary") or "").strip() \
        if info["review"].get("decision") in ("ACCEPT", "ACCEPT_PARTIAL") else ""
    summary = review_summary or template_summary(info, outcome)
    report_rel = rel(report, repo)

    commit = None
    if run.get("commit"):
        message = commit_message(info, outcome, summary, report_rel)
        commit = do_commit(repo, directory, info, outcome, message)
    prose, data = render_report(info, state, outcome, summary, commit, report_rel)
    report.write_text(prose + "\n```json\n" + json.dumps(data, indent=2, ensure_ascii=False)
                      + "\n```\n", encoding="utf-8")
    run["finished"] = {"outcome": outcome, "at": _now(), "commit": commit}
    c.save_run(directory, run)
    return 0, prose


def cmd_finish(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        directory = c.run_dir(repo, args.slug, args.run)
        code, text = do_finish(repo, directory)
    except c.CheckError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(text, file=sys.stdout if code == 0 else sys.stderr)
    return code


# ------------------------------------------------------------------- main ---


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start")
    s.add_argument("slug")
    s.add_argument("--repo", default=".")
    s.add_argument("--mode", default="legacy")
    s.add_argument("--interactive", action="store_true")
    s.add_argument("--spec", default=None)
    s.add_argument("--impl-cap", type=int, default=3)
    s.add_argument("--plan-cap", type=int, default=2)
    s.add_argument("--commit", action="store_true",
                   help="commit the run's test files on DONE / DONE_PARTIAL (never on a protected branch)")

    for name in ("state", "reseal", "finish"):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.add_argument("--repo", default=".")
        p.add_argument("--run", default="latest")

    args = parser.parse_args()
    return {"start": cmd_start, "state": cmd_state, "reseal": cmd_reseal,
            "finish": cmd_finish}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
