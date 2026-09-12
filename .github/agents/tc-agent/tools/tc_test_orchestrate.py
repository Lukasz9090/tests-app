#!/usr/bin/env python3
"""Decision-table tests for the pipeline control flow — DEV TOOL, not runtime.

`tc_orchestrate.py state` is the brain of the pipeline: every "what next" the
Orchestrator agent performs comes from it, and the agent is forbidden to
second-guess it. A wrong verdict here is invisible — the run simply stops early,
repeats a round, or reports work as finished while a review finding is still
open. None of that raises an error, so only a test catches it.

Covered:
  * every branch of `compute_state` (PLAN / GENERATE / REVIEW / DONE / ESCALATE),
    both caps, and the paths carried in `dispatch`,
  * `surface`, which is the only way the Orchestrator (no file-reading tool)
    learns about `unimplementable`, `suggestions`, and a working tree the run
    left with failing tests,
  * `scenarios_in_scope` — the two-axis rule that decides what is left to build,
  * artifact selection in `tc_common` (`load_report`, `latest`), where a glob once
    matched v10 for plan v1,
  * the `ledger` subcommand, where reading must not create the file.

Standard library only, no pytest, no maven: every case writes small markdown
artifacts into a temporary repository. Runs in well under a second.

Usage:
    python .github/agents/tc-agent/tools/tc_test_orchestrate.py [--verbose]

Exit codes (same discipline as the Reviewer scripts):
    0 — every case passed
    1 — at least one case failed (each printed with expected vs actual)
    2 — the harness could not run (imports, arguments)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
TC = HERE.parents[1]
ORCHESTRATE = TC / "scripts" / "tc_orchestrate.py"
sys.path.insert(0, str(TC / "scripts"))

try:
    import tc_orchestrate as o
    import tc_common as c
except ImportError as exc:  # pragma: no cover - environment problem, not a defect
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)


# ----------------------------------------------------------------- harness ---

FAILURES: list = []
PASSED = 0
VERBOSE = False


def expect(label: str, actual, wanted) -> None:
    """One assertion. Never raises: a failing case must not hide the later ones."""
    global PASSED
    if actual == wanted:
        PASSED += 1
        if VERBOSE:
            print(f"  ok   {label}")
        return
    FAILURES.append(f"{label}\n         wanted: {wanted!r}\n         actual: {actual!r}")
    print(f"  FAIL {label}")


class Repo:
    """A temporary repository holding only `.test-agent/plans/<slug>` artifacts."""

    SLUG = "T"

    def __init__(self, directory: Path):
        self.root = directory
        self.plans = directory / ".test-agent" / "plans" / self.SLUG
        self.plans.mkdir(parents=True)

    # --- artifacts ---------------------------------------------------------

    def write(self, name: str, payload: dict) -> Path:
        """Artifacts are markdown containers: prose plus exactly one json fence."""
        path = self.plans / name
        path.write_text(
            f"# {name}\n\nhuman summary\n\n```json\n"
            f"{json.dumps(payload, indent=2)}\n```\n",
            encoding="utf-8",
        )
        return path

    def broken(self, name: str) -> Path:
        path = self.plans / name
        path.write_text("# no fence here at all\n", encoding="utf-8")
        return path

    def plan(self, version: int, status: str, scenarios: list, based_on: int | None = None):
        payload = {
            "schema_version": 1,
            "plan_version": version,
            "target": {"class": "T"},
            "mode": "legacy",
            "characterization": True,
            "status": status,
            "scenarios": scenarios,
            "deferred": [],
        }
        if based_on:
            payload["based_on_version"] = based_on
        return self.write(f"plan-v{version}.md", payload)

    def report(self, version: int, iteration: int = 1, suggestions: list | None = None):
        name = (f"generation-report-v{version}.md" if iteration == 1
                else f"generation-report-v{version}-r{iteration}.md")
        payload = {
            "schema_version": 1,
            "plan_version": version,
            "target": {"class": "T"},
            "test_files": ["src/test/java/TTest.java"],
            "results": [{"id": "TC01", "status": "IMPLEMENTED", "test_method": "a"}],
        }
        if suggestions is not None:
            payload["suggestions"] = suggestions
        return self.write(name, payload)

    def review(self, version: int, iteration: int, decision: str,
               feedback: list | None = None, unimplementable: list | None = None):
        payload = {
            "schema_version": 1,
            "plan_version": version,
            "generation_report": f"generation-report-v{version}.md",
            "review_iteration": iteration,
            "target": {"class": "T"},
            "mode": "legacy",
            "decision": decision,
            "checks": {"compile": {"status": "PASSED"}, "tests": {"status": "PASSED"}},
            "findings": [],
        }
        if feedback is not None:
            payload["feedback"] = {"implementation": feedback}
        if unimplementable is not None:
            payload["unimplementable"] = unimplementable
        return self.write(f"review-v{version}-r{iteration}.md", payload)

    # --- queries -----------------------------------------------------------

    def state(self, impl_cap: int = 3, plan_cap: int = 5) -> dict:
        return o.compute_state(self.root, self.SLUG, impl_cap, plan_cap)


def scenario(tc="TC01", change="NEW", implementation="PENDING", **extra) -> dict:
    out = {
        "id": tc,
        "change": change,
        "description": "a behaviour worth testing",
        "priority": "high",
        "evidence": [{"type": "usage", "ref": "src/main/java/T.java:10"}],
    }
    if implementation:
        out["implementation"] = implementation
    out.update(extra)
    return out


PENDING = scenario()
COVERED = scenario(change="UNCHANGED", implementation="COVERED", covered_by="TTest#a")
REMOVED = scenario(change="REMOVED", implementation="PENDING",
                   change_reason="the branch was deleted in commit abc123")
FEEDBACK = [{"tc": ["TC01"], "location": "TTest.java:30", "request": "assert the status too"}]
SUGGESTIONS = [{"related": ["TC01"], "suggestion": "inject java.time.Clock",
                "rationale": "makes the guard testable"}]
UNIMPLEMENTABLE = [{"id": "TC09", "reason": "no Clock seam"}]


def case(name: str):
    """Decorator-free case runner: each test gets a fresh temporary repository.

    A case that raises is a failure like any other, never the end of the run:
    one broken branch must not hide the verdict of the twenty after it.
    """
    def run(body):
        print(f"\n{name}")
        try:
            with tempfile.TemporaryDirectory() as directory:
                body(Repo(Path(directory)))
        except Exception as exc:
            FAILURES.append(f"{name}\n         raised: {type(exc).__name__}: {exc}")
            print(f"  FAIL raised {type(exc).__name__}: {exc}")
    return run


# ------------------------------------------------------------------- cases ---


def test_no_plan():
    @case("no artifacts at all -> PLAN v1")
    def _(repo):
        state = repo.state()
        expect("next_action", state["next_action"], "PLAN")
        expect("dispatch.plan_version", state["dispatch"]["plan_version"], 1)
        expect("surface is always present, with all three keys", state["surface"],
               {"unimplementable": [], "suggestions": [], "working_tree": {}})


def test_unparseable_plan():
    @case("plan without a json fence -> ESCALATE, never a guess")
    def _(repo):
        repo.broken("plan-v1.md")
        state = repo.state()
        expect("next_action", state["next_action"], "ESCALATE")
        expect("reason names the file", "plan-v1.md" in state["reason"], True)


def test_plan_stop_statuses():
    for status in ("BLOCKED", "NEEDS_CLARIFICATION", "UNSUPPORTED_REPOSITORY"):
        @case(f"plan status {status} -> ESCALATE (a human decides)")
        def _(repo, status=status):
            repo.plan(1, status, [PENDING])
            expect("next_action", repo.state()["next_action"], "ESCALATE")


def test_unknown_plan_status():
    @case("unrecognized plan status -> ESCALATE, not a default route")
    def _(repo):
        repo.plan(1, "ALMOST_READY", [PENDING])
        expect("next_action", repo.state()["next_action"], "ESCALATE")


def test_first_generation():
    @case("READY plan, no generation yet -> GENERATE round 1")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        state = repo.state()
        expect("next_action", state["next_action"], "GENERATE")
        expect("iteration", state["dispatch"]["iteration"], 1)
        expect("report path is repo-relative posix, as every agent file writes it",
               state["dispatch"]["report_path"],
               ".test-agent/plans/T/generation-report-v1.md")
        expect("plan path too", state["plan"]["path"], ".test-agent/plans/T/plan-v1.md")
        expect("no review to carry", state["dispatch"]["carry_review_path"], None)
        expect("scenarios_in_scope", state["plan"]["scenarios_in_scope"], ["TC01"])


def test_awaiting_review():
    @case("generation exists, no review for it -> REVIEW")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        state = repo.state()
        expect("next_action", state["next_action"], "REVIEW")
        expect("iteration", state["dispatch"]["iteration"], 1)


def test_accept_paths():
    for decision in ("ACCEPT", "ACCEPT_PARTIAL"):
        @case(f"reviewer decided {decision} -> DONE with surface filled")
        def _(repo, decision=decision):
            repo.plan(1, "READY", [PENDING])
            repo.report(1, suggestions=SUGGESTIONS)
            repo.review(1, 1, decision, unimplementable=UNIMPLEMENTABLE)
            state = repo.state()
            expect("next_action", state["next_action"], "DONE")
            expect("surface.unimplementable", state["surface"]["unimplementable"],
                   UNIMPLEMENTABLE)
            expect("surface.suggestions", state["surface"]["suggestions"], SUGGESTIONS)


def test_human_decisions():
    for decision in ("NEEDS_TRIAGE", "BLOCKED"):
        @case(f"reviewer decided {decision} -> ESCALATE (never auto-confirmed)")
        def _(repo, decision=decision):
            repo.plan(1, "READY", [PENDING])
            repo.report(1)
            repo.review(1, 1, decision)
            expect("next_action", repo.state()["next_action"], "ESCALATE")


def test_unknown_decision():
    @case("unrecognized review decision -> ESCALATE")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "LOOKS_FINE")
        expect("next_action", repo.state()["next_action"], "ESCALATE")


def test_unparseable_review():
    @case("review without a json fence -> ESCALATE")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.broken("review-v1-r1.md")
        state = repo.state()
        expect("next_action", state["next_action"], "ESCALATE")
        expect("reason names the file", "review-v1-r1.md" in state["reason"], True)


def test_repair_implementation():
    @case("REPAIR_IMPLEMENTATION below the cap -> GENERATE round 2 with the review")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_IMPLEMENTATION", feedback=FEEDBACK)
        state = repo.state(impl_cap=3)
        expect("next_action", state["next_action"], "GENERATE")
        expect("iteration", state["dispatch"]["iteration"], 2)
        expect("report carries the -r2 suffix",
               Path(state["dispatch"]["report_path"]).name, "generation-report-v1-r2.md")
        expect("prior_review_path",
               Path(state["dispatch"]["prior_review_path"]).name, "review-v1-r1.md")
        expect("open feedback is reported",
               state["review"]["has_open_impl_feedback"], True)


def test_impl_cap():
    @case("REPAIR_IMPLEMENTATION at the cap -> ESCALATE, never one more round")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.report(1, iteration=2)
        repo.review(1, 2, "REPAIR_IMPLEMENTATION", feedback=FEEDBACK)
        state = repo.state(impl_cap=2)
        expect("next_action", state["next_action"], "ESCALATE")
        expect("reason names the cap", "impl_cap 2" in state["reason"], True)
        expect("surface still reaches the user", "surface" in state, True)


def test_repair_plan():
    @case("REPAIR_PLAN below the cap -> PLAN v2 carrying both prior artifacts")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_PLAN", feedback=FEEDBACK)
        state = repo.state(plan_cap=2)
        dispatch = state["dispatch"]
        expect("next_action", state["next_action"], "PLAN")
        expect("plan_version", dispatch["plan_version"], 2)
        expect("based_on_version", dispatch["based_on_version"], 1)
        expect("prior_generation_report_path",
               Path(dispatch["prior_generation_report_path"]).name,
               "generation-report-v1.md")
        expect("carry_review_path", Path(dispatch["carry_review_path"]).name,
               "review-v1-r1.md")


def test_repair_plan_without_feedback():
    @case("REPAIR_PLAN with no implementation feedback -> nothing to carry")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_PLAN")
        expect("carry_review_path", repo.state()["dispatch"]["carry_review_path"], None)


def test_plan_cap():
    @case("REPAIR_PLAN at the cap -> ESCALATE")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.plan(2, "READY", [PENDING], based_on=1)
        repo.report(2)
        repo.review(2, 1, "REPAIR_PLAN", feedback=FEEDBACK)
        state = repo.state(plan_cap=2)
        expect("next_action", state["next_action"], "ESCALATE")
        expect("reason names the cap", "plan_cap 2" in state["reason"], True)


def test_carry_survives_plan_bump():
    @case("first generation of a bumped plan still carries the v1 finding")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_PLAN", feedback=FEEDBACK)
        repo.plan(2, "READY", [PENDING], based_on=1)
        state = repo.state()
        expect("next_action", state["next_action"], "GENERATE")
        expect("carry_review_path", Path(state["dispatch"]["carry_review_path"]).name,
               "review-v1-r1.md")


def test_carry_closed_by_accept():
    @case("a later ACCEPT closes the finding -> nothing is carried")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_IMPLEMENTATION", feedback=FEEDBACK)
        repo.report(1, iteration=2)
        repo.review(1, 2, "ACCEPT")
        repo.plan(2, "READY", [PENDING], based_on=1)
        expect("carry_review_path", repo.state()["dispatch"]["carry_review_path"], None)


def test_complete_plan():
    @case("COMPLETE plan -> DONE (a success state, not a cancellation)")
    def _(repo):
        repo.plan(1, "COMPLETE", [COVERED])
        state = repo.state()
        expect("next_action", state["next_action"], "DONE")
        expect("reason says implemented", "already implemented" in state["reason"], True)


def test_complete_plan_with_open_feedback():
    @case("COMPLETE plan with an open finding -> ESCALATE, the finding is not lost")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1, suggestions=SUGGESTIONS)
        repo.review(1, 1, "REPAIR_PLAN", feedback=FEEDBACK, unimplementable=UNIMPLEMENTABLE)
        repo.plan(2, "COMPLETE", [COVERED], based_on=1)
        state = repo.state()
        expect("next_action", state["next_action"], "ESCALATE")
        expect("reason names the review", "review-v1-r1.md" in state["reason"], True)
        expect("surface.unimplementable", state["surface"]["unimplementable"],
               UNIMPLEMENTABLE)
        expect("surface.suggestions come from the v1 report",
               state["surface"]["suggestions"], SUGGESTIONS)


def test_nothing_in_scope():
    @case("READY plan with every scenario covered -> DONE, no empty generation")
    def _(repo):
        repo.plan(1, "READY", [COVERED])
        state = repo.state()
        expect("next_action", state["next_action"], "DONE")
        expect("scenarios_in_scope", state["plan"]["scenarios_in_scope"], [])


def test_nothing_in_scope_with_open_feedback():
    @case("nothing in scope but a finding is open -> ESCALATE")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_PLAN", feedback=FEEDBACK)
        repo.plan(2, "READY", [COVERED], based_on=1)
        expect("next_action", repo.state()["next_action"], "ESCALATE")


def test_scenarios_in_scope():
    @case("scenarios_in_scope: the two-axis rule")
    def _(repo):
        plan = {"scenarios": [
            scenario("TC01"),                                             # PENDING
            scenario("TC02", change="MODIFIED", implementation="BLOCKED"),
            COVERED | {"id": "TC03"},                                     # out: covered
            REMOVED | {"id": "TC04"},                                     # out: gone
            {"id": "TC05", "change": "NEW"},                              # absent = PENDING
            "not a dict",                                                 # ignored
        ]}
        expect("only work that is left", o.scenarios_in_scope(plan),
               ["TC01", "TC02", "TC05"])


def test_report_selection():
    @case("artifact selection: plan v1 must not read the report of plan v10")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.report(10)
        repo.report(1, iteration=2)
        path, _ = c.load_report(repo.root, repo.SLUG, 1)
        expect("newest report of v1", path.name, "generation-report-v1-r2.md")
        path, _ = c.load_report(repo.root, repo.SLUG, 10)
        expect("report of v10", path.name, "generation-report-v10.md")


def test_plan_selection():
    @case("artifact selection: the highest plan version wins, v10 > v9")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.plan(9, "READY", [PENDING])
        repo.plan(10, "READY", [PENDING])
        path, _ = c.load_plan(repo.root, repo.SLUG)
        expect("latest plan", path.name, "plan-v10.md")
        expect("state uses it", repo.state()["plan"]["version"], 10)


def _check_report(repo, name: str, payload: dict) -> None:
    """Write a tests-r<M>.md the way tc_run_tests.py would."""
    checks = repo.root / ".test-agent" / "checks" / repo.SLUG
    checks.mkdir(parents=True, exist_ok=True)
    (checks / name).write_text(
        "# Check: tests\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n",
        encoding="utf-8",
    )


def test_working_tree_red():
    @case("a run that stops at the cap must surface the tests it leaves red")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_IMPLEMENTATION", feedback=FEEDBACK)
        _check_report(repo, "tests-r1.md", {
            "status": "FAILED", "total": 11, "failed": 1,
            "failures": [{"test": "TTest#shouldSkip", "failure_phase": "setup",
                          "location": "TTest.java:200",
                          "message": "Invalid use of argument matchers!"}],
        })

        state = repo.state(impl_cap=1)
        tree = state["surface"]["working_tree"]
        expect("next_action", state["next_action"], "ESCALATE")
        expect("the red tree is reported", tree.get("tests_red"), True)
        expect("the failing test is named",
               [f["test"] for f in tree.get("failures", [])], ["TTest#shouldSkip"])
        expect("with its location", tree["failures"][0]["location"], "TTest.java:200")
        expect("report path is repo-relative", tree.get("report"),
               ".test-agent/checks/T/tests-r1.md")


def test_working_tree_green():
    @case("a green run surfaces no working-tree warning")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "ACCEPT")
        _check_report(repo, "tests-r1.md",
                      {"status": "PASSED", "total": 11, "failed": 0, "failures": []})
        state = repo.state()
        expect("next_action", state["next_action"], "DONE")
        expect("nothing to warn about", state["surface"]["working_tree"], {})


def test_working_tree_compile_error():
    @case("a tree that does not compile is reported as red too")
    def _(repo):
        repo.plan(1, "READY", [PENDING])
        repo.report(1)
        repo.review(1, 1, "REPAIR_IMPLEMENTATION", feedback=FEEDBACK)
        _check_report(repo, "tests-r1.md",
                      {"status": "PASSED", "total": 11, "failed": 0, "failures": []})
        _check_report(repo, "tests-r2.md",
                      {"status": "COMPILE_ERROR",
                       "compiler_errors": ["TTest.java:12 cannot find symbol"]})
        tree = repo.state(impl_cap=1)["surface"]["working_tree"]
        expect("red", tree.get("tests_red"), True)
        expect("the compiler line is carried", tree.get("compile_errors"),
               ["TTest.java:12 cannot find symbol"])
        expect("newest report wins, not the first",
               tree.get("report"), ".test-agent/checks/T/tests-r2.md")


def test_ledger():
    @case("ledger: reading is read-only, writing appends")
    def _(repo):
        ledger = repo.plans / "run-ledger.md"
        command = [sys.executable, str(ORCHESTRATE), "ledger", repo.SLUG,
                   "--repo", str(repo.root)]
        result = subprocess.run(command, capture_output=True, text=True)
        expect("exit code", result.returncode, 0)
        expect("a read creates no file", ledger.exists(), False)

        subprocess.run(command + ["--event", '{"phase":"PLAN","note":"x"}'],
                       capture_output=True, text=True)
        expect("--event creates it", ledger.exists(), True)
        subprocess.run(command + ["--event", '{"phase":"GENERATE","note":"y"}'],
                       capture_output=True, text=True)
        subprocess.run(command + ["--outcome", "DONE"], capture_output=True, text=True)
        payload, _ = o.load_payload(ledger)
        expect("history is appended, never replaced", len(payload["history"]), 2)
        expect("every entry is timestamped",
               all("ts" in entry for entry in payload["history"]), True)
        expect("outcome", payload["outcome"], "DONE")
        expect("status", payload["status"], "DONE")


# -------------------------------------------------------------------- main ---


def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="print passing assertions too")
    VERBOSE = parser.parse_args().verbose

    for name, body in sorted(globals().items()):
        if name.startswith("test_") and callable(body):
            body()

    print(f"\n{PASSED + len(FAILURES)} assertions: {PASSED} passed, {len(FAILURES)} failed")
    if FAILURES:
        print("\nFAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PIPELINE_CONTROL_FLOW_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
