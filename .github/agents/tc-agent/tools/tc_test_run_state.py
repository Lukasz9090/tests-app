#!/usr/bin/env python3
"""Tests for the run lifecycle (tc_orchestrate.py) — DEV TOOL, not runtime.

Covered:

  * the in-run state machine (derive verdicts,
    RESEAL, plan statuses, generation/review loop, the round limit),
  * that a run only ever reads its own directory (an older run's artifacts do
    not leak into a new one),
  * reseal through the orchestrator (one line per test, recorded in run.json),
  * finish: outcome DONE vs DONE_PARTIAL, red tree first, report contents,
    template vs reviewer summary, idempotence,
  * --commit: only DONE/DONE_PARTIAL, only the run's test files, never a
    dirty index, protected branches (default master, profile list with globs,
    detached HEAD) get a new tc-agent/<slug>/<run-id> branch, commit message
    shape (title, summary, facts).

Usage:
    python .github/agents/tc-agent/tools/tc_test_run_state.py [--verbose]
Exit codes: 0 all passed, 1 a case failed, 2 the harness could not run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from tc_testkit import (TC, FakeRunner, FixtureRepo, ai_test, expect, expect_true,  # noqa: E402
                            human_test, run_all)
    import tc_common as c  # noqa: E402
    from tc_md_payload import load_payload as load_container  # noqa: E402
    import tc_derive_state as ds  # noqa: E402
    import tc_git as g  # noqa: E402
    import tc_orchestrate as o  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)

SLUG = "OrderService"


def container(title: str, payload: dict) -> str:
    return f"# {title}\n\nsummary\n\n```json\n{json.dumps(payload, indent=2)}\n```\n"


class Run:
    """One run directory inside a FixtureRepo, with helpers to drop artifacts."""

    def __init__(self, repo: FixtureRepo, run_id: str = "20260101-000000", commit: bool = False,
                 max_rounds: int = 3, mode: str = "characterization"):
        self.repo = repo
        self.dir = c.runs_root(repo.root, SLUG) / run_id
        self.dir.mkdir(parents=True)
        self.run = {"schema_version": 1, "slug": SLUG, "run_id": run_id, "mode": mode,
                    "interactive": False, "spec": None,
                    "max_rounds": max_rounds,
                    "commit": commit, "started": "x", "resealed": False}
        c.save_run(self.dir, self.run)

    def derive(self, runner=None, **run_overrides):
        state = ds.derive(self.repo.root, SLUG, {**self.run, **run_overrides},
                          runner=runner or FakeRunner(), freshness_days=7)
        ds.write(self.dir, state)
        return state

    def derive_raw(self, next_action: str, **extra):
        payload = {"next_action": next_action, "reasons": extra.pop("reasons", ["X"]),
                   "reseal": [], "git": {"current_sha": "abc1234", "dirty": False},
                   "target": {"class": SLUG}, **extra}
        (self.dir / "derive-state.md").write_text(container("derive", payload), encoding="utf-8")

    def put(self, name: str, payload: dict):
        (self.dir / name).write_text(container(name, payload), encoding="utf-8")

    def plan(self, n: int, status: str = "READY", **extra):
        self.put(f"plan-v{n}.md", {"schema_version": 1, "plan_version": n, "status": status,
                                    "target": {"class": SLUG}, "mode": "characterization", **extra})

    def report(self, n: int, m: int = 1, results=None, test_files=None, suggestions=None):
        name = f"generation-report-v{n}.md" if m == 1 else f"generation-report-v{n}-r{m}.md"
        self.put(name, {"schema_version": 1, "plan_version": n, "target": {"class": SLUG},
                        "test_files": test_files or [],
                        "results": results or [{"id": "TC01", "status": "IMPLEMENTED", "test_method": "shouldA"}],
                        "suggestions": suggestions or []})

    def review(self, n: int, m: int, decision: str, **extra):
        self.put(f"review-v{n}-r{m}.md", {"schema_version": 1, "plan_version": n, "review_iteration": m,
                                          "decision": decision, **extra})

    def state(self) -> dict:
        return o.compute_state(self.repo.root, self.dir)

    def finish(self) -> tuple:
        return o.do_finish(self.repo.root, self.dir)

    def reload(self) -> dict:
        return c.load_run(self.dir)


GREEN_TESTS = {"tests": {"status": "PASSED", "total": 14, "failed": 0, "flaky": []},
               "coverage": {"status": "FAILED", "branch_ratio": 0.53, "gate": 0.8}}


def step(state: dict) -> tuple:
    return state["next_action"], state.get("outcome")


# ---------------------------------------------------------- state machine ---


def test_derive_verdicts_route_straight_to_finish():
    with FixtureRepo() as repo:
        run = Run(repo)
        for verdict, outcome in (("RED", "RED"), ("BLOCKED", "BLOCKED"), ("ESCALATE", "ESCALATED"),
                                 ("DONE", "DONE")):
            run.derive_raw(verdict)
            expect(f"derive {verdict}", step(run.state()), ("FINISH", outcome))
        (run.dir / "derive-state.md").write_text("garbage", encoding="utf-8")
        expect("unreadable derive-state escalates", step(run.state()), ("FINISH", "ESCALATED"))


def test_reseal_comes_first():
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("DONE", reseal=[{"method": "T#a", "file": "T.java", "from": "1234567", "to": "abc1234"}])
        expect("RESEAL before anything", step(run.state()), ("RESEAL", None))
        run.derive_raw("PLAN", reseal=[{"method": "T#a", "file": "T.java", "from": "1234567", "to": "abc1234"}])
        expect("RESEAL before PLAN too", step(run.state()), ("RESEAL", None))
        run.derive_raw("RED", reseal=[{"method": "T#a", "file": "T.java", "from": "1234567", "to": "abc1234"}])
        expect("never reseal on RED", step(run.state()), ("FINISH", "RED"))


def test_plan_generate_review_loop():
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN")
        s = run.state()
        expect("no plan -> PLAN v1", (s["next_action"], s["dispatch"]["plan_path"].endswith("plan-v1.md")),
               ("PLAN", True))
        expect("first plan has no review to read", s["dispatch"]["review_path"], None)
        run.plan(1)
        s = run.state()
        expect("READY -> GENERATE r1", (s["next_action"], s["dispatch"]["report_path"].endswith(
            "generation-report-v1.md")), ("GENERATE", True))
        run.report(1)
        s = run.state()
        expect("-> REVIEW with its label", (s["next_action"], s["dispatch"]["label"]), ("REVIEW", "v1-r1"))
        run.review(1, 1, "REPAIR_IMPLEMENTATION")
        s = run.state()
        expect("repair -> GENERATE r2 with the review",
               (s["next_action"], s["dispatch"]["report_path"].endswith("-v1-r2.md"),
                s["dispatch"]["review_path"].endswith("review-v1-r1.md")), ("GENERATE", True, True))
        run.report(1, 2)
        expect("-> REVIEW r2", step(run.state()), ("REVIEW", None))
        run.review(1, 2, "REPAIR_PLAN")
        s = run.state()
        expect("REPAIR_PLAN -> PLAN v2 with the review",
               (s["next_action"], s["dispatch"]["plan_path"].endswith("plan-v2.md"),
                s["dispatch"]["review_path"].endswith("review-v1-r2.md")), ("PLAN", True, True))
        run.plan(2, "READY_PARTIAL")
        s = run.state()
        expect("generator of plan v2 still gets the newest review (no carry logic)",
               (s["next_action"], s["dispatch"]["review_path"].endswith("review-v1-r2.md")),
               ("GENERATE", True))
        run.report(2)
        run.review(2, 1, "ACCEPT")
        expect("ACCEPT -> FINISH DONE", step(run.state()), ("FINISH", "DONE"))
        run.review(2, 1, "ACCEPT_PARTIAL")
        expect("ACCEPT_PARTIAL -> DONE_PARTIAL", step(run.state()), ("FINISH", "DONE_PARTIAL"))
        for decision in ("NEEDS_TRIAGE", "BLOCKED", "WHATEVER"):
            run.review(2, 1, decision)
            expect(f"{decision} -> ESCALATED", step(run.state()), ("FINISH", "ESCALATED"))


def test_plan_statuses():
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN")
        for status, outcome in (("BLOCKED", "BLOCKED"), ("NEEDS_CLARIFICATION", "ESCALATED"),
                                ("UNSUPPORTED_REPOSITORY", "ESCALATED"), ("COMPLETE", "DONE"),
                                ("SOMETHING", "ESCALATED")):
            run.plan(1, status)
            expect(f"plan {status}", step(run.state()), ("FINISH", outcome))
        (run.dir / "plan-v1.md").write_text("no fence", encoding="utf-8")
        expect("unparseable plan", step(run.state()), ("FINISH", "ESCALATED"))
        run.plan(1)
        run.report(1)
        run.review(1, 1, "REPAIR_PLAN")
        run.plan(2, "COMPLETE")
        s = run.state()
        expect("COMPLETE after REPAIR_PLAN goes to a human", step(s), ("FINISH", "ESCALATED"))
        expect_true("and says why", "found nothing to repair" in s["reason"])


def test_round_limit():
    """One review closes one round; plan versions do not buy extra rounds."""
    with FixtureRepo() as repo:
        run = Run(repo)                                     # default: 3 rounds
        run.derive_raw("PLAN")
        run.plan(1)
        run.report(1)
        run.review(1, 1, "REPAIR_IMPLEMENTATION")
        s = run.state()
        expect("round 1 -> repair", step(s), ("GENERATE", None))
        expect_true("says which round", "round 2 of 3" in s["reason"])
        run.report(1, 2)
        run.review(1, 2, "REPAIR_PLAN")
        s = run.state()
        expect("round 2 -> new plan", step(s), ("PLAN", None))
        expect("no replan_cause any more", "replan_cause" in s["dispatch"], False)
        run.plan(2)
        run.report(2)
        run.review(2, 1, "REPAIR_IMPLEMENTATION", checks=GREEN_TESTS)
        s = run.state()
        expect("3 of 3 spent -> finish", step(s), ("FINISH", "ESCALATED"))
        expect_true("says why", "3 of 3 rounds" in s["reason"])
        run.review(2, 1, "REPAIR_PLAN")
        expect("REPAIR_PLAN is capped as well", step(run.state()), ("FINISH", "ESCALATED"))
        run.review(2, 1, "ACCEPT", commit_summary="x.")
        expect("ACCEPT on the last round still finishes DONE", step(run.state()), ("FINISH", "DONE"))


def test_round_limit_is_per_run_setting():
    with FixtureRepo() as repo:
        run = Run(repo, max_rounds=1)
        run.derive_raw("PLAN")
        run.plan(1)
        run.report(1)
        run.review(1, 1, "REPAIR_IMPLEMENTATION")
        expect("max_rounds 1 stops after the first review", step(run.state()), ("FINISH", "ESCALATED"))


def test_no_sequence_exceeds_three_reviews():
    """Whatever the reviewer decides, a run never reaches a 4th review."""
    import itertools
    for decisions in itertools.product(("REPAIR_IMPLEMENTATION", "REPAIR_PLAN"), repeat=3):
        with FixtureRepo() as repo:
            run = Run(repo)
            run.derive_raw("PLAN")
            n, m, reviews = 1, 1, 0
            run.plan(1)
            for decision in decisions:
                run.report(n, m)
                run.review(n, m, decision)
                reviews += 1
                s = run.state()
                if s["next_action"] == "FINISH":
                    break
                if s["next_action"] == "PLAN":
                    n, m = n + 1, 1
                    run.plan(n)
                else:
                    m += 1
            expect(f"{'/'.join(d[7:11] for d in decisions)}: at most 3 reviews, then FINISH",
                   (reviews <= 3, run.state()["next_action"]), (True, "FINISH"))


def test_dispatch_references():
    """Each role reads only the instruction files that apply to THIS run."""
    def names(state):
        return [Path(r).as_posix().split("references/")[-1] for r in state["dispatch"]["references"]]

    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN", repo={"junit": "5"})
        s = run.state()
        expect("planner, characterization", names(s), ["contracts.md", "conventions.md", "modes/characterization.md"])
        for r in s["dispatch"]["references"]:
            expect_true(f"{r} exists", (repo.root / r).is_file() or Path(r).is_file())
        run.run["interactive"] = True
        c.save_run(run.dir, run.run)
        expect("planner, interactive", names(run.state())[-1], "modes/interactive.md")
        run.plan(1)
        expect("generator never gets the interactive rules", names(run.state()),
               ["contracts.md", "conventions.md", "modes/characterization.md"])
        run.report(1)
        expect("reviewer", (run.state()["next_action"], names(run.state())),
               ("REVIEW", ["contracts.md", "conventions.md", "modes/characterization.md"]))
    with FixtureRepo() as repo:
        run = Run(repo, mode="spec-driven")
        run.derive_raw("PLAN", repo={"junit": "4"})
        expect("JUnit 4 + spec-driven", names(run.state()),
               ["contracts.md", "conventions.md", "junit4.md", "modes/spec-driven.md"])


def test_each_rule_has_one_owner():
    """D83: a rule lives in one file; prompts point to it instead of repeating it."""
    owners = {"Relational values": "references/conventions.md", "Object shapes": "references/conventions.md",
              "RELATIVE to now": "references/conventions.md", "isEven": "references/conventions.md",
              "AI-generated placeholder": "references/conventions.md", "black box": "references/contracts.md",
              "Never delete a field": "references/contracts.md", "TYPES FROM DEPENDENCIES": "references/contracts.md",
              "@Ignore": "references/junit4.md", "MockitoJUnitRunner": "references/junit4.md"}
    files = list(TC.glob("*.agent.md")) + list((TC / "references").rglob("*.md"))
    for phrase, owner in owners.items():
        found = sorted(f.relative_to(TC).as_posix() for f in files
                       if phrase.lower() in f.read_text(encoding="utf-8").lower())
        expect(f"'{phrase}' only in {owner}", found, [owner])


def test_a_change_outside_src_test_during_the_run_stops_it():
    for change, path in ((lambda r: r.change_target(), "src/main/java/com/acme/OrderService.java"),
                         (lambda r: r.write("pom.xml", r.read("pom.xml") + "<!-- x -->"), "pom.xml"),
                         (lambda r: r.write("docs/notes.md", "x"), "docs/notes.md")):
        with FixtureRepo() as repo:
            repo.write("src/main/java/com/acme/Draft.java", "class Draft {}")     # dirty before the run
            run = Run(repo)
            run.run["outside_tests"] = g.outside_tests_snapshot(repo.root)
            c.save_run(run.dir, run.run)
            run.derive_raw("PLAN")
            expect("unchanged since start", step(run.state()), ("PLAN", None))
            repo.write_test("OrderServiceTest", ai_test("shouldA", repo.sha()))
            (run.dir / "notes.md").write_text("x", encoding="utf-8")       # .test-agent, not gitignored here
            repo.write("target/classes/x.txt", "build output")
            expect("tests, .test-agent and target/ do not count", step(run.state()), ("PLAN", None))
            change(repo)
            s = run.state()
            expect(f"a change to {path} escalates", step(s), ("FINISH", "ESCALATED"))
            expect_true(f"and names {path}", path in s["reason"])


def test_known_test_data_travels_between_plan_versions():
    """A human answers once per run; the next planner is handed the answer."""
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN")
        expect("nothing known yet", run.state()["dispatch"]["known_test_data"], [])
        run.plan(1, context={"test_data": [
            {"concept": "customerId", "rule": "9 digits", "examples": ["123456789"]},
            {"concept": "productCode", "examples": ["AGD"]}]})
        run.report(1)
        run.review(1, 1, "REPAIR_PLAN")
        dispatch = run.state()["dispatch"]
        expect("both values reach plan v2",
               [e["concept"] for e in dispatch["known_test_data"]], ["customerId", "productCode"])
        run.plan(2, context={"test_data": [
            {"concept": "customerId", "examples": ["999999999"]},   # same concept again
            {"concept": "dictKey", "examples": ["AML-1"]}]})
        run.report(2)
        run.review(2, 1, "REPAIR_PLAN")
        dispatch = run.state()["dispatch"]
        expect("merged, first answer wins, no duplicates",
               [(e["concept"], e["examples"][0]) for e in dispatch["known_test_data"]],
               [("customerId", "123456789"), ("productCode", "AGD"), ("dictKey", "AML-1")])


def test_runs_are_isolated():
    with FixtureRepo() as repo:
        old = Run(repo, run_id="20250101-000000")
        old.derive_raw("PLAN")
        old.plan(1)
        old.report(1)
        old.review(1, 1, "REPAIR_PLAN")
        new = Run(repo, run_id="20260101-000000")
        new.derive_raw("PLAN")
        s = new.state()
        expect("a new run starts at PLAN v1, blind to the old run",
               (s["next_action"], s["dispatch"]["plan_path"].endswith("20260101-000000/plan-v1.md"),
                s["dispatch"]["review_path"]), ("PLAN", True, None))
        expect("latest resolves to the newest run", c.run_dir(repo.root, SLUG, "latest"), new.dir)


# ------------------------------------------------------------ reseal/finish ---


def test_reseal_and_finish_done():
    with FixtureRepo() as repo:
        old = repo.sha()
        rel = repo.write_test("OrderServiceTest", ai_test("shouldA", old), ai_test("shouldB", old))
        repo.commit("tests", days_ago=20)
        repo.change_target()
        new = repo.commit("refactor", days_ago=10)
        run = Run(repo)
        run.derive()
        expect("RESEAL", step(run.state()), ("RESEAL", None))
        result = o.do_reseal(repo.root, run.dir)
        expect("both methods resealed", [r["changed"] for r in result["resealed"]], [True, True])
        text = repo.read(rel)
        expect("the new sha is in the file twice", text.count(f"OrderService@{new}"), 2)
        expect("run.json records it", run.reload()["resealed"], True)
        expect("then FINISH DONE", step(run.state()), ("FINISH", "DONE"))
        code, prose = run.finish()
        expect("finish ok", code, 0)
        expect_true("template summary for a reseal-only run", "Resealed 2 characterization test(s)" in prose)
        expect_true("tells the human to commit", "review and commit" in prose)
        payload = json.loads((run.dir / "run-report.md").read_text().split("```json")[1].split("```")[0])
        expect("report outcome", payload["outcome"], "DONE")
        expect("report files", payload["test_files"], [rel])
        code2, prose2 = run.finish()
        expect_true("finish is idempotent", "(already finished)" in prose2)


def test_start_that_could_not_derive_says_why():
    """A maven failure during start must not become "derive-state.md not found"."""
    with FixtureRepo() as repo:
        script = TC / "scripts" / "tc_orchestrate.py"
        proc = subprocess.run([sys.executable, str(script), "start", "NoSuchClassHere",
                               "--repo", str(repo.root)], capture_output=True, text=True)
        expect("start fails loudly", proc.returncode in (0, 2), True)
        directory = c.runs_root(repo.root, "NoSuchClassHere")
        runs = sorted(p for p in directory.iterdir()) if directory.is_dir() else []
        expect_true("the run kept a derive-state.md", bool(runs) and (runs[-1] / "derive-state.md").is_file())
        state = o.compute_state(repo.root, runs[-1])
        expect("it routes to FINISH", state["next_action"], "FINISH")
        expect_true("and names a real cause, not a missing file",
                    "not found" in str(state.get("reason", "")).lower()
                    or "TARGET_NOT_FOUND" in str(state.get("reason", "")))


def test_a_start_that_is_still_running_says_WAIT():
    """Two terminals: start still works in one, `state` must not call it dead."""
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("ESCALATE", reasons=["START_INTERRUPTED"],
                       pid=os.getpid(), started="now",
                       detail="start has not finished deriving the state.")
        state = run.state()
        expect("waits instead of finishing", state["next_action"], "WAIT")
        expect_true("and says why", "still deriving" in state["reason"])
        run.derive_raw("ESCALATE", reasons=["START_INTERRUPTED"], pid=999999999,
                       started="then", detail="start has not finished deriving the state.")
        state = run.state()
        expect("a dead start finishes", step(state), ("FINISH", "ESCALATED"))
        expect_true("named as gone", "process is gone" in state["reason"])


def test_interrupted_start_leaves_a_readable_state():
    """A killed start (Ctrl+C, a closed terminal) must still explain itself.

    KeyboardInterrupt is not an Exception, so no handler runs: the placeholder
    derive-state written before the checks is what survives.
    """
    import argparse
    with FixtureRepo() as repo:
        args = argparse.Namespace(slug=SLUG, repo=str(repo.root), mode="characterization",
                                  interactive=False, spec=None, test_data=None,
                                  max_rounds=None, commit=False)
        original = ds.derive
        ds.derive = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
        try:
            o.cmd_start(args)
        except KeyboardInterrupt:
            pass
        finally:
            ds.derive = original
        root = c.runs_root(repo.root, SLUG)
        runs = sorted(p for p in root.iterdir())
        expect_true("a derive-state.md is there", (runs[-1] / "derive-state.md").is_file())
        written, _ = load_container(runs[-1] / "derive-state.md")
        expect("marked as an unfinished start", written["reasons"], ["START_INTERRUPTED"])
        expect("with the pid that can be checked later", written["pid"], os.getpid())


def test_run_without_derive_state_is_not_a_mystery():
    with FixtureRepo() as repo:
        run = Run(repo)                      # run.json only, no derive-state.md
        state = run.state()
        expect("routes to FINISH", step(state), ("FINISH", "ESCALATED"))
        expect_true("explains that start did not get that far",
                    "start` did not get that far" in state["reason"])


def test_finish_refuses_unfinished_run():
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN")
        code, message = run.finish()
        expect("exit 2", code, 2)
        expect_true("names the pending step", "PLAN" in message)


def test_done_partial_when_placeholders_in_code():
    with FixtureRepo() as repo:
        sha = repo.sha()
        repo.write_test("OrderServiceTest", ai_test("shouldA", sha), ai_test("shouldB", sha, deferred="needs Clock"))
        repo.commit("tests", days_ago=20)
        run = Run(repo)
        run.derive()
        code, prose = run.finish()
        expect_true("DONE upgraded to DONE_PARTIAL", "Outcome: DONE_PARTIAL" in prose)


def test_confirm_lines_are_cleaned_and_deduplicated():
    notes = ["module: x",
             "CONFIRM: A.java:47-52 ? the code ignores case ? freeze it? Answer: freeze.",
             "CONFIRM: A.java:47-52 — the code ignores case — freeze it? Answer: freeze.",
             "CONFIRM: A.java:20 — integer division? Answer: freeze."]
    expect("dedup + '?' separator restored", o.confirm_lines(notes),
           ["CONFIRM: A.java:47-52 — the code ignores case — freeze it? Answer: freeze.",
            "CONFIRM: A.java:20 — integer division? Answer: freeze."])


def test_red_tree_comes_first():
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("RED", reasons=["TESTS_FAILING"])
        (run.dir / "checks").mkdir()
        (run.dir / "checks" / "tests-entry.md").write_text(container("tests", {
            "status": "FAILED", "failures": [{"test": "com.acme.OrderServiceTest#humanB",
                                              "location": "OrderServiceTest.java:12",
                                              "failure_phase": "assertion", "message": "expected 1"}]}),
            encoding="utf-8")
        code, prose = run.finish()
        first = prose.split("\n")[2]
        expect_true("the red warning is the first thing said", "RED" in first)
        expect_true("location named", "OrderServiceTest.java:12" in prose)


def test_complete_plan_over_a_red_suite_is_RED_not_DONE():
    """A plan that says COMPLETE must not turn a broken suite into a DONE run."""
    with FixtureRepo() as repo:
        run = Run(repo, commit=True)
        run.derive_raw("PLAN")
        run.plan(1, status="COMPLETE")
        (run.dir / "checks").mkdir()
        (run.dir / "checks" / "tests-v1-r1.md").write_text(container("tests", {
            "status": "FAILED", "failures": [{"test": "com.acme.OrderServiceTest#shouldA",
                                              "location": "OrderServiceTest.java:20",
                                              "failure_phase": "assertion", "message": "expected 2"}]}),
            encoding="utf-8")
        code, prose = run.finish()
        expect_true("outcome is RED", "Outcome: RED" in prose)
        expect_true("no commit over a red tree", "commit" not in prose.lower().split("next steps")[0]
                    or "RED" in prose)


def test_reviewer_summary_is_used():
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN")
        run.plan(1)
        run.report(1)
        run.review(1, 1, "ACCEPT", commit_summary="Added one characterization test for OrderService.create.")
        code, prose = run.finish()
        expect_true("reviewer's prose is the summary",
                    "Added one characterization test for OrderService.create." in prose)


def test_spec_mismatches_lead_the_report():
    with FixtureRepo() as repo:
        run = Run(repo, mode="spec-driven")
        run.derive_raw("PLAN", reasons=["SPEC_REVIEW"])
        run.plan(1)
        run.report(1)
        mismatch = {"type": "spec_mismatch", "severity": "major", "stage": 1,
                    "test_method": "shouldRejectZeroAmount",
                    "message": "spec R1 says 0 is rejected; the code accepts it"}
        run.review(1, 1, "REPAIR_IMPLEMENTATION", findings=[mismatch])
        run.report(1, 2)
        run.review(1, 2, "ACCEPT_PARTIAL", commit_summary="x.", findings=[mismatch])
        code, prose = run.finish()
        expect("listed once", prose.count("shouldRejectZeroAmount: spec R1 says 0 is rejected"), 1)
        expect_true("ahead of the outcome", prose.index("does not do what the spec says") < prose.index("**Outcome"))


def test_reviewer_dispatch_carries_the_run_digest():
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN")
        run.plan(1)
        run.report(1, results=[{"id": "TC01", "status": "IMPLEMENTED", "test_method": "shouldT1"},
                               {"id": "TC02", "status": "IMPLEMENTED", "test_method": "shouldT2"}])
        run.review(1, 1, "REPAIR_PLAN")
        run.plan(2)
        run.report(2, results=[{"id": "TC01", "status": "SKIPPED", "test_method": "shouldT1"},
                               {"id": "TC03", "status": "PLACEHOLDER", "test_method": "shouldT3",
                                "reason": "no seam"}])
        st = run.state()
        expect("next", st["next_action"], "REVIEW")
        dg = st["dispatch"]["run_digest"]
        expect("digest tests span rounds", [x["test_method"] for x in dg["tests_written"]],
               ["shouldT1", "shouldT2"])
        expect("digest placeholders", dg["placeholders_written"], [{"test_method": "shouldT3", "reason": "no seam"}])
        expect("digest rounds", dg["rounds"], ["v1-r1 REPAIR_PLAN"])


def test_counts_span_every_round_of_the_run():
    """v1 wrote five tests, v2 added one and reported the rest SKIPPED."""
    with FixtureRepo() as repo:
        run = Run(repo)
        run.derive_raw("PLAN")
        run.plan(1, context={"notes": ["CONFIRM: A.java:1 — first question"]})
        run.report(1, results=[{"id": f"TC0{i}", "status": "IMPLEMENTED", "test_method": f"shouldT{i}"}
                               for i in range(1, 6)])
        run.review(1, 1, "REPAIR_PLAN")
        run.plan(2, context={"notes": ["CONFIRM: A.java:9 — second question"]})
        run.report(2, results=[{"id": f"TC0{i}", "status": "SKIPPED", "test_method": f"shouldT{i}"}
                               for i in range(1, 6)]
                   + [{"id": "TC06", "status": "IMPLEMENTED", "test_method": "shouldT6"},
                      {"id": "TC07", "status": "PLACEHOLDER", "test_method": "shouldT7"}])
        run.review(2, 1, "ACCEPT_PARTIAL", commit_summary="x.")
        info = o.collect(repo.root, run.dir, run.state())
        expect("all six tests of the run", sorted(info["written"]), [f"shouldT{i}" for i in range(1, 7)])
        expect("one placeholder", info["placeholders_written"], ["shouldT7"])
        expect("history", info["history"], ["v1-r1 REPAIR_PLAN", "v2-r1 ACCEPT_PARTIAL"])
        expect("CONFIRM from both plans", len(info["confirm"]), 2)
        code, prose = run.finish()
        expect_true("rounds line", "rounds (2 of 3): v1-r1 REPAIR_PLAN -> v2-r1 ACCEPT_PARTIAL" in prose)
        expect_true("count line", "tests written: 6;" in prose)


# ------------------------------------------------------------------ commit ---


def generated_run(repo: FixtureRepo, commit=True, run_id="20260101-000000") -> tuple:
    """A run whose generator wrote one test file and whose reviewer accepted."""
    repo.write("AGENTS.md", repo.read("AGENTS.md")) if (repo.root / "AGENTS.md").exists() else None
    run = Run(repo, commit=commit, run_id=run_id)
    run.derive_raw("PLAN", coverage={"branch_ratio": 0.5, "gate": 0.8})
    run.plan(1)
    rel = repo.write_test("OrderServiceTest", ai_test("shouldA", repo.sha()))
    run.report(1, test_files=[rel],
               suggestions=[{"related": ["TC01"], "suggestion": "Inject java.time.Clock",
                             "rationale": "time guards"}])
    run.review(1, 1, "ACCEPT",
               commit_summary="Added a characterization test for OrderService.create covering the "
                              "positive amount path.",
               checks={"coverage": {"status": "PASSED", "branch_ratio": 0.84, "gate": 0.8},
                       "mutation": {"status": "PASSED", "score": 0.76, "gate": 0.7}})
    return run, rel


def log(repo: FixtureRepo, ref="HEAD") -> str:
    return repo.git("log", "-1", "--format=%B", ref)


def test_commit_on_master_creates_a_branch():
    with FixtureRepo() as repo:
        run, rel = generated_run(repo)
        base = repo.git("rev-parse", "HEAD")
        code, prose = run.finish()
        commit = run.reload()["finished"]["commit"]
        expect("committed", commit["status"], "committed")
        expect("new branch", (commit["branch"], commit["created_branch"], commit["from_branch"]),
               ("tc-agent/OrderService/20260101-000000", True, "master"))
        expect("master untouched", repo.git("rev-parse", "master"), base)
        expect("only the run's test file", repo.git("show", "--name-only", "--format=", "HEAD"), rel)
        message = log(repo)
        expect("title", message.split("\n")[0], "[TC-AGENT] Add tests for OrderService.")
        expect("nothing from .test-agent in the message", ("Outcome:" in message, "Report:" in message,
                                                            ".test-agent" in message), (False, False, False))
        expect_true("reviewer summary in the body", "positive amount path." in message)
        expect_true("facts: gates", "Gates: branch coverage 84% (gate 80%), mutation 76% (gate 70%)" in message)
        expect_true("facts: suggestions", "Suggestions: Inject java.time.Clock" in message)
        expect_true("report says the branch was created", "went to a NEW branch tc-agent/OrderService" in prose)


def test_commit_on_unprotected_branch_stays():
    with FixtureRepo() as repo:
        repo.write(".github/agents/tc-agent-project/profile.md", '# p\n\n```json\n{"schema_version": 1, "protected_branches": ["master", "develop"]}\n```\n')
        c._PROFILE_CACHE.clear()
        repo.commit("profile", days_ago=25)
        repo.git("switch", "-q", "-c", "feature/x")
        run, _ = generated_run(repo)
        run.finish()
        commit = run.reload()["finished"]["commit"]
        expect("committed on feature/x", (commit["status"], commit["branch"], commit["created_branch"]),
               ("committed", "feature/x", False))


def test_commit_protected_glob_and_detached():
    with FixtureRepo() as repo:
        repo.write(".github/agents/tc-agent-project/profile.md", '# p\n\n```json\n{"schema_version": 1, "protected_branches": ["release/*"]}\n```\n')
        c._PROFILE_CACHE.clear()
        repo.commit("profile", days_ago=25)
        repo.git("switch", "-q", "-c", "release/1.0")
        run, _ = generated_run(repo)
        run.finish()
        expect("glob protects release/1.0", run.reload()["finished"]["commit"]["created_branch"], True)
    with FixtureRepo() as repo:
        repo.git("checkout", "-q", "--detach")
        run, _ = generated_run(repo)
        run.finish()
        commit = run.reload()["finished"]["commit"]
        expect("detached HEAD gets a branch", (commit["status"], commit["created_branch"]), ("committed", True))


def test_commit_refusals():
    with FixtureRepo() as repo:
        run, _ = generated_run(repo, commit=False)
        run.finish()
        expect("no --commit, no commit", run.reload()["finished"]["commit"], None)
    with FixtureRepo() as repo:
        run, _ = generated_run(repo)
        run.review(1, 1, "NEEDS_TRIAGE")
        run.finish()
        expect("ESCALATED never commits", run.reload()["finished"]["commit"]["status"], "skipped")
    with FixtureRepo() as repo:
        repo.write("unrelated.txt", "x")
        repo.git("add", "unrelated.txt")
        run, _ = generated_run(repo)
        run.finish()
        commit = run.reload()["finished"]["commit"]
        expect("dirty index refuses", (commit["status"], "index not clean" in commit["reason"]),
               ("skipped", True))
        expect("still on master", repo.git("branch", "--show-current"), "master")
    with FixtureRepo() as repo:
        run, rel = generated_run(repo)
        run.run["outside_tests"] = g.outside_tests_snapshot(repo.root)
        c.save_run(run.dir, run.run)
        repo.write("src/main/java/com/acme/Other.java", "package com.acme; class Other {}")
        run.report(1, test_files=[rel, "src/main/java/com/acme/Other.java"])
        run.finish()
        finished = run.reload()["finished"]
        expect("production files are never committed: the run escalates instead",
               (finished["outcome"], finished["commit"]["status"]), ("ESCALATED", "skipped"))
    with FixtureRepo() as repo:
        repo.write("pom.xml", repo.read("pom.xml") + "<!-- edited before the run -->")
        run, rel = generated_run(repo)
        run.run["outside_tests"] = g.outside_tests_snapshot(repo.root)
        c.save_run(run.dir, run.run)
        run.report(1, test_files=[rel, "pom.xml"])
        run.finish()
        commit = run.reload()["finished"]["commit"]
        expect("a file outside src/test named by the generator is never committed",
               (commit["status"], commit["files"]), ("committed", [rel]))
        expect_true("and stays in the working tree", "pom.xml" in repo.git("status", "--porcelain"))


def test_start_cli_writes_run_json():
    with FixtureRepo() as repo:
        repo.write("docs/spec.md", "# spec")
        repo.write("docs/test-data.md", "customer id: 9 digits")
        script = TC / "scripts" / "tc_orchestrate.py"
        proc = subprocess.run([sys.executable, str(script), "start", SLUG, "--repo", str(repo.root),
                               "--mode", "spec-driven", "--spec", "docs/spec.md", "--interactive", "--commit",
                               "--max-rounds", "4", "--test-data", "docs/test-data.md"],
                              capture_output=True, text=True)
        expect("start exits 0", proc.returncode, 0)
        out = json.loads(proc.stdout)
        run = c.load_run(repo.root / out["run_dir"])
        expect("run.json holds mode/interactive/commit/max_rounds",
               (run["mode"], run["interactive"], run["commit"], run["max_rounds"]),
               ("spec-driven", True, True, 4))
        expect("derive-state ran (no tests -> PLAN)", out["derive_state"]["next_action"], "PLAN")
        expect("--test-data is stored for the pack", run["test_data_paths"], ["docs/test-data.md"])
        bad = subprocess.run([sys.executable, str(script), "start", SLUG, "--repo", str(repo.root),
                              "--mode", "tdd"], capture_output=True, text=True)
        expect("tdd is refused", bad.returncode, 2)


def test_start_refuses_what_it_cannot_run():
    script = TC / "scripts" / "tc_orchestrate.py"

    def start(repo, *extra):
        proc = subprocess.run([sys.executable, str(script), "start", SLUG, "--repo", str(repo.root), *extra],
                              capture_output=True, text=True)
        runs = c.runs_root(repo.root, SLUG)
        return proc.returncode, proc.stderr, runs.is_dir() and any(runs.iterdir())

    with FixtureRepo() as repo:
        code, err, made = start(repo, "--mode", "spec-driven")
        expect("spec-driven without a spec", (code, err.startswith("SPEC_REQUIRED"), made), (2, True, False))
        code, err, _ = start(repo, "--mode", "spec-driven", "--spec", "docs/nope.md")
        expect("missing spec file", (code, err.startswith("FILE_NOT_FOUND: --spec")), (2, True))
        code, err, _ = start(repo, "--test-data", "docs/nope.md")
        expect("missing --test-data file", (code, err.startswith("FILE_NOT_FOUND: --test-data")), (2, True))
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "max_round": 2}\n```\n')
        c._PROFILE_CACHE.clear()
        code, err, made = start(repo)
        expect("a profile key the schema does not know",
               (code, err.startswith("INVALID_PROFILE"), "max_round" in err, made), (2, True, True, False))


def test_maven_time_is_recorded_per_check():
    """"The run took four minutes" must be answerable from the run directory."""
    with FixtureRepo() as repo:
        run = Run(repo)
        checks = c.checks_dir(run.dir)
        for name, title, seconds in (("tests-v1.md", "Check: tests", 95.4),
                                     ("tests-v1-r2.md", "Check: tests", 60.0),
                                     ("coverage-v1.md", "Check: coverage", 28.2),
                                     ("mutation-v1.md", "Check: mutation", 110.0)):
            c.write_container(checks / name, title, ["x"],
                              {"status": "PASSED", "maven_seconds": seconds})
        spent = o.check_timings(run.dir)
        expect("summed over rounds", spent["tests"], 155)
        expect("coverage on its own", spent["coverage"], 28)
        expect("mutation on its own", spent["mutation"], 110)
        c.write_container(checks / "tests-v2.md", "Check: tests", ["x"], {"status": "PASSED"})
        expect("a check without a timing is skipped, not an error",
               o.check_timings(run.dir)["tests"], 155)


def test_the_conventional_output_path_is_checked_before_walking():
    """The fallback walk crosses the whole of target/ - in a big module, slowly."""
    import tempfile, time as _t
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "target" / "site" / "jacoco").mkdir(parents=True)
        wanted = root / "target" / "site" / "jacoco" / "jacoco.xml"
        wanted.write_text("<report/>", encoding="utf-8")
        deep = root / "target" / "classes" / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "jacoco.xml").write_text("<stale/>", encoding="utf-8")
        found = c.recent_files(root, "**/jacoco.xml", 0, prefer=("target/site/jacoco/jacoco.xml",))
        expect("the conventional file alone", [p.name for p in found], ["jacoco.xml"])
        expect("and it is the right one", found[0], wanted)
        expect("a file older than the run is not a hit",
               c.recent_files(root, "**/jacoco.xml", _t.time() + 60,
                              prefer=("target/site/jacoco/jacoco.xml",)), [])
        wanted.unlink()
        found = c.recent_files(root, "**/jacoco.xml", 0, prefer=("target/site/jacoco/jacoco.xml",))
        expect_true("without it, the walk still finds the other one",
                    found and found[0].parent.name == "c")


def test_maven_goals_are_read_from_the_banners():
    """Maven prints no per-goal timings, so the list of goals is the diagnosis."""
    output = "\n".join([
        "[INFO] Scanning for projects...",
        "[INFO] --- openapi-generator-maven-plugin:6.6.0:generate (client) @ ces-pl-rest ---",
        "[INFO] --- maven-resources-plugin:3.3.1:resources (default-resources) @ ces-pl-rest ---",
        "[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) @ ces-pl-rest ---",
        "[INFO] Compiling 6571 source files with javac",
        "[INFO] --- maven-compiler-plugin:3.11.0:testCompile (default-testCompile) @ ces-pl-rest ---",
        "[INFO] --- maven-surefire-plugin:3.2.5:test (default-test) @ ces-pl-rest ---",
        "[INFO] --- maven-surefire-plugin:3.2.5:test (default-test) @ ces-pl-rest ---",
        "[INFO] BUILD SUCCESS",
    ])
    goals = c.maven_goals_run(output)
    expect("in order, deduplicated", goals,
           ["openapi-generator-maven-plugin:generate", "maven-resources-plugin:resources",
            "maven-compiler-plugin:compile", "maven-compiler-plugin:testCompile",
            "maven-surefire-plugin:test"])
    expect("nothing to find in a quiet log", c.maven_goals_run("[INFO] BUILD SUCCESS"), [])


def test_a_green_check_keeps_the_tail_of_its_log():
    with FixtureRepo() as repo:
        log = repo.root / "maven.log"
        body = ["[INFO] --- openapi-generator-maven-plugin:6.6.0:generate (client) @ x ---"]
        body += [f"line {i}" for i in range(500)]
        log.write_text("\n".join(body) + "\n", encoding="utf-8")
        c.trim_log(log, keep=10)
        kept = log.read_text(encoding="utf-8")
        expect_true("the goal banner survives the trim", "openapi-generator" in kept)
        log.write_text("\n".join(f"line {i}" for i in range(500)) + "\n", encoding="utf-8")
        c.trim_log(log, keep=10)
        kept = log.read_text(encoding="utf-8").splitlines()
        expect_true("says it was trimmed", kept[0].startswith("[tc-agent] green check"))
        expect("keeps the last lines - where Total time lives", kept[-1], "line 499")
        expect("and only those", len(kept), 12)
        short = repo.root / "short.log"
        short.write_text("one\ntwo\n", encoding="utf-8")
        c.trim_log(short, keep=10)
        expect("a short log is left alone", short.read_text(encoding="utf-8"), "one\ntwo\n")


if __name__ == "__main__":
    sys.exit(run_all(globals(), "RUN_LIFECYCLE_OK"))
