#!/usr/bin/env python3
"""Tests for the run lifecycle (tc_orchestrate.py) — DEV TOOL, not runtime.

Replaces the Model A tc_test_orchestrate.py. Covered:

  * the in-run state machine: every row of MODEL-B-PLAN §5.4 (derive verdicts,
    RESEAL, plan statuses, generation/review loop, both caps),
  * that a run only ever reads its own directory (an older run's artifacts do
    not leak into a new one),
  * reseal through the orchestrator (one line per test, recorded in run.json),
  * finish: outcome DONE vs DONE_PARTIAL, red tree first, report contents,
    template vs reviewer summary, idempotence,
  * --commit: only DONE/DONE_PARTIAL, only the run's test files, never a
    dirty index, protected branches (default master, AGENTS.md list with globs,
    detached HEAD) get a new tc-agent/<slug>/<run-id> branch, commit message
    shape (title, summary, facts).

Usage:
    python .github/agents/tc-agent/tools/tc_test_run_state.py [--verbose]
Exit codes: 0 all passed, 1 a case failed, 2 the harness could not run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from tc_testkit import (TC, FakeRunner, FixtureRepo, ai_test, expect, expect_true,  # noqa: E402
                            human_test, run_all)
    import tc_common as c  # noqa: E402
    import tc_derive_state as ds  # noqa: E402
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
                 impl_cap: int = 3, plan_cap: int = 2, mode: str = "legacy"):
        self.repo = repo
        self.dir = c.runs_root(repo.root, SLUG) / run_id
        self.dir.mkdir(parents=True)
        self.run = {"schema_version": 1, "slug": SLUG, "run_id": run_id, "mode": mode,
                    "interactive": False, "spec": None,
                    "caps": {"impl_cap": impl_cap, "plan_cap": plan_cap},
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
                                    "target": {"class": SLUG}, "mode": "legacy", **extra})

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


def test_caps():
    with FixtureRepo() as repo:
        run = Run(repo, impl_cap=2, plan_cap=1)
        run.derive_raw("PLAN")
        run.plan(1)
        run.report(1)
        run.review(1, 1, "REPAIR_IMPLEMENTATION")
        expect("below impl_cap", step(run.state()), ("GENERATE", None))
        run.report(1, 2)
        run.review(1, 2, "REPAIR_IMPLEMENTATION")
        s = run.state()
        expect("impl_cap reached", step(s), ("FINISH", "ESCALATED"))
        expect_true("says why", "impl_cap 2" in s["reason"])
        run.review(1, 2, "REPAIR_PLAN")
        s = run.state()
        expect("plan_cap reached", step(s), ("FINISH", "ESCALATED"))
        expect_true("says why", "plan_cap 1" in s["reason"])


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
        expect("title", message.split("\n")[0], "test(OrderService): tc-agent DONE [run 20260101-000000]")
        expect_true("reviewer summary in the body", "positive amount path." in message)
        expect_true("facts: gates", "Gates: branch coverage 84% (gate 80%), mutation 76% (gate 70%)" in message)
        expect_true("facts: suggestions", "Suggestions: Inject java.time.Clock" in message)
        expect_true("facts: report path", "run-report.md" in message)
        expect_true("report says the branch was created", "went to a NEW branch tc-agent/OrderService" in prose)


def test_commit_on_unprotected_branch_stays():
    with FixtureRepo() as repo:
        repo.write("AGENTS.md", "tc-agent-protected-branches: master, develop\n")
        repo.commit("agents", days_ago=25)
        repo.git("switch", "-q", "-c", "feature/x")
        run, _ = generated_run(repo)
        run.finish()
        commit = run.reload()["finished"]["commit"]
        expect("committed on feature/x", (commit["status"], commit["branch"], commit["created_branch"]),
               ("committed", "feature/x", False))


def test_commit_protected_glob_and_detached():
    with FixtureRepo() as repo:
        repo.write("AGENTS.md", "tc-agent-protected-branches: release/*\n")
        repo.commit("agents", days_ago=25)
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
        repo.write("src/main/java/com/acme/Other.java", "package com.acme; class Other {}")
        run.report(1, test_files=[rel, "src/main/java/com/acme/Other.java"])
        run.finish()
        files = run.reload()["finished"]["commit"]["files"]
        expect("production files are never committed", files, [rel])


def test_start_cli_writes_run_json():
    with FixtureRepo() as repo:
        script = TC / "scripts" / "tc_orchestrate.py"
        proc = subprocess.run([sys.executable, str(script), "start", SLUG, "--repo", str(repo.root),
                               "--mode", "spec-driven", "--interactive", "--commit", "--impl-cap", "4"],
                              capture_output=True, text=True)
        expect("start exits 0", proc.returncode, 0)
        out = json.loads(proc.stdout)
        run = c.load_run(repo.root / out["run_dir"])
        expect("run.json holds mode/interactive/commit/caps",
               (run["mode"], run["interactive"], run["commit"], run["caps"]["impl_cap"]),
               ("spec-driven", True, True, 4))
        expect("derive-state ran (no tests -> PLAN)", out["derive_state"]["next_action"], "PLAN")
        bad = subprocess.run([sys.executable, str(script), "start", SLUG, "--repo", str(repo.root),
                              "--mode", "tdd"], capture_output=True, text=True)
        expect("tdd is refused", bad.returncode, 2)


if __name__ == "__main__":
    sys.exit(run_all(globals(), "RUN_LIFECYCLE_OK"))
