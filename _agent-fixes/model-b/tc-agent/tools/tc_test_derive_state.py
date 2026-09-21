#!/usr/bin/env python3
"""Decision tests for derive-state (tc_derive_state.py) — DEV TOOL, not runtime.

derive-state is the only place Model B decides what a target needs, and it does
so from the real world: a fixture git repository with real commits, dirty files
and aged history. Only the maven-driven checks (tests, coverage, PIT) are
replaced by a fake runner with canned reports.

Covered: every verdict (PLAN / DONE / RED / BLOCKED / ESCALATE) and reason,
tier short-circuits (which checks ran), staleness with prefix-matched shas,
reseal vs recharacterize, stale placeholders, the freshness guard for legacy
(dirty, too fresh, interactive, spec-driven, custom freshness_days), and the
written derive-state.md.

Usage:
    python .github/agents/tc-agent/tools/tc_test_derive_state.py [--verbose]
Exit codes: 0 all passed, 1 a case failed, 2 the harness could not run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from tc_testkit import (FakeRunner, FixtureRepo, ai_test, expect, expect_true,  # noqa: E402
                            failing, human_test, run_all)
    import tc_derive_state as ds  # noqa: E402
    from tc_md_payload import load_payload  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)


def run(mode="legacy", interactive=False) -> dict:
    return {"run_id": "r1", "mode": mode, "interactive": interactive}


def derive(repo, runner=None, slug="OrderService", **kw):
    fresh = kw.pop("freshness_days", 7)
    return ds.derive(repo.root, slug, run(**kw), runner=runner or FakeRunner(), freshness_days=fresh)


def test_unknown_target_escalates():
    with FixtureRepo() as repo:
        state = derive(repo, slug="Nope")
        expect("ESCALATE", (state["next_action"], state["reasons"]), ("ESCALATE", ["TARGET_NOT_FOUND"]))


def test_no_tests_plans_without_building():
    with FixtureRepo() as repo:
        runner = FakeRunner()
        state = derive(repo, runner)
        expect("PLAN / NO_TESTS", (state["next_action"], state["reasons"]), ("PLAN", ["NO_TESTS"]))
        expect("no check ran", runner.calls, [])
        expect("tiers", state["tiers_run"], [0, 1])


def test_all_green_is_done():
    with FixtureRepo() as repo:
        sha = repo.sha()
        repo.write_test("OrderServiceTest", ai_test("shouldA", sha), human_test("humanB"))
        repo.commit("tests", days_ago=20)
        runner = FakeRunner()
        state = derive(repo, runner)
        expect("DONE", (state["next_action"], state["reasons"]), ("DONE", ["GATES_MET"]))
        expect("all three tiers ran", runner.calls, ["tests", "coverage", "mutation"])
        expect("counts", (len(state["tests"]["ai"]), state["tests"]["human_count"]), (1, 1))
        expect("nothing stale", state["tests"]["stale"], [])


def test_human_tests_only_with_gap_plans():
    """Case 2: human tests are measured like any other; the gap drives the plan."""
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", human_test("humanB"))
        repo.commit("tests", days_ago=20)
        runner = FakeRunner(coverage=(1, {"status": "FAILED", "branch_ratio": 0.5, "gate": 0.8,
                                         "uncovered": [{"line": 6, "missed_branches": 1}]}))
        state = derive(repo, runner)
        expect("PLAN / COVERAGE_GAP", (state["next_action"], state["reasons"]), ("PLAN", ["COVERAGE_GAP"]))
        expect("PIT skipped once coverage decided", runner.calls, ["tests", "coverage"])
        expect("uncovered lines handed to the planner", state["coverage"]["uncovered"],
               [{"line": 6, "missed_branches": 1}])


def test_mutation_gap_plans():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", human_test("humanB"))
        repo.commit("tests", days_ago=20)
        runner = FakeRunner(mutation=(1, {"status": "FAILED", "score": 0.4, "gate": 0.7,
                                         "survivors": [{"line": 5, "mutator": "X"}]}))
        state = derive(repo, runner)
        expect("PLAN / MUTATION_GAP", (state["next_action"], state["reasons"]), ("PLAN", ["MUTATION_GAP"]))
        expect("survivors kept", state["mutation"]["survivors"], [{"line": 5, "mutator": "X"}])


def test_stale_green_is_resealed_not_planned():
    """Case 1a: the code moved, the frozen behaviour did not."""
    with FixtureRepo() as repo:
        old = repo.sha()
        repo.write_test("OrderServiceTest", ai_test("shouldA", old))
        repo.commit("tests", days_ago=20)
        repo.change_target()
        new = repo.commit("refactor", days_ago=10)
        state = derive(repo)
        expect("still DONE", state["next_action"], "DONE")
        expect("stale detected", state["tests"]["stale"], ["OrderServiceTest#shouldA"])
        expect("reseal entry", state["reseal"],
               [{"method": "OrderServiceTest#shouldA", "file": "src/test/java/com/acme/OrderServiceTest.java",
                 "from": old, "to": new}])
        expect("nothing to recharacterize", state["recharacterize"], [])


def test_stale_red_is_recharacterized():
    """Case 1b: the frozen behaviour changed. Not RED: the planner re-freezes it."""
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", ai_test("shouldA", repo.sha()), human_test("humanB"))
        repo.commit("tests", days_ago=20)
        repo.change_target("return amount * 2;")
        repo.commit("behaviour change", days_ago=10)
        runner = FakeRunner(tests=failing("com.acme.OrderServiceTest#shouldA"))
        state = derive(repo, runner)
        expect("PLAN / STALE", (state["next_action"], state["reasons"]), ("PLAN", ["STALE"]))
        expect("recharacterize", [r["method"] for r in state["recharacterize"]], ["OrderServiceTest#shouldA"])
        expect("not red", state["red"], [])


def test_sha_prefix_is_not_stale():
    with FixtureRepo() as repo:
        full = repo.git("rev-parse", "HEAD")
        repo.write_test("OrderServiceTest", ai_test("shouldA", full[:12]))
        repo.commit("tests", days_ago=20)
        state = derive(repo)
        expect("a longer abbreviation still matches", state["tests"]["stale"], [])


def test_other_class_characterization_is_ignored():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", ai_test("shouldA", "1234567", cls="PaymentService"),
                        "    OrderService s;\n")
        repo.commit("tests", days_ago=20)
        state = derive(repo)
        expect("staleness only for tc-agent-characterizes <Target>", state["tests"]["stale"], [])


def test_red_human_test_stops():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", human_test("humanB"))
        repo.commit("tests", days_ago=20)
        runner = FakeRunner(tests=failing("com.acme.OrderServiceTest#humanB(int)[1]"))
        state = derive(repo, runner)
        expect("RED", (state["next_action"], state["reasons"]), ("RED", ["TESTS_FAILING"]))
        expect("red names the test", state["red"][0]["test"], "com.acme.OrderServiceTest#humanB(int)[1]")
        expect("coverage never ran", runner.calls, ["tests"])


def test_red_fresh_ai_test_stops():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", ai_test("shouldA", repo.sha()))
        repo.commit("tests", days_ago=20)
        state = derive(repo, FakeRunner(tests=failing("com.acme.OrderServiceTest#shouldA")))
        expect("a non-stale AI test failing is RED, not a re-plan", state["next_action"], "RED")


def test_compile_error_is_red():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", human_test("humanB"))
        repo.commit("tests", days_ago=20)
        state = derive(repo, FakeRunner(tests=(1, {"status": "COMPILE_ERROR",
                                                   "compiler_errors": ["X.java:3 cannot find symbol"]})))
        expect("RED / COMPILE_ERROR", (state["next_action"], state["reasons"]), ("RED", ["COMPILE_ERROR"]))
        expect("errors kept", state["compile_errors"], ["X.java:3 cannot find symbol"])


def test_unavailable_check_escalates():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", human_test("humanB"))
        repo.commit("tests", days_ago=20)
        for label, runner in (
            ("tests", FakeRunner(tests=(2, {"status": "UNAVAILABLE", "reason": "no mvn"}))),
            ("coverage", FakeRunner(coverage=(2, {"status": "UNAVAILABLE", "reason": "empty exec"}))),
            ("mutation", FakeRunner(mutation=(2, {"status": "SKIPPED_UNAVAILABLE", "reason": "no junit5 plugin"}))),
        ):
            state = derive(repo, runner)
            expect(f"exit 2 in {label} is never a pass", (state["next_action"], state["reasons"]),
                   ("ESCALATE", ["CHECK_UNAVAILABLE"]))


def test_placeholders_are_reported_and_stale_ones_replanned():
    with FixtureRepo() as repo:
        sha = repo.sha()
        repo.write_test("OrderServiceTest", ai_test("shouldA", sha),
                        ai_test("shouldB", sha, deferred="needs a Clock seam"))
        repo.commit("tests", days_ago=20)
        state = derive(repo)
        expect("placeholder listed", [p["method"] for p in state["tests"]["placeholders"]],
               ["OrderServiceTest#shouldB"])
        expect("not counted as an AI test", len(state["tests"]["ai"]), 1)
        expect("DONE when gates are met", state["next_action"], "DONE")

        repo.change_target()
        repo.commit("refactor", days_ago=10)
        state = derive(repo)
        expect("stale placeholder goes to the planner", [r["method"] for r in state["recharacterize"]],
               ["OrderServiceTest#shouldB"])
        expect("stale green test is resealed", [r["method"] for r in state["reseal"]],
               ["OrderServiceTest#shouldA"])
        expect("PLAN / STALE", (state["next_action"], state["reasons"]), ("PLAN", ["STALE"]))


def test_freshness_guard():
    with FixtureRepo() as repo:
        repo.change_target()
        repo.commit("fresh change", days_ago=2)
        state = derive(repo)
        expect("legacy + fresh -> BLOCKED", (state["next_action"], state["reasons"]),
               ("BLOCKED", ["TARGET_TOO_FRESH", "NO_TESTS"]))
        expect_true("the detail tells the user what to do", "--interactive" in state["detail"])
        expect("interactive lets the planner ask", derive(repo, interactive=True)["next_action"], "PLAN")
        expect("spec-driven has no guard", derive(repo, mode="spec-driven")["next_action"], "PLAN")
        expect("freshness_days from the profile", derive(repo, freshness_days=1)["next_action"], "PLAN")


def test_dirty_blocks_even_interactive():
    with FixtureRepo() as repo:
        repo.change_target("return amount - 0;")
        for interactive in (False, True):
            state = derive(repo, interactive=interactive)
            expect(f"dirty legacy blocks (interactive={interactive})",
                   (state["next_action"], state["reasons"][0]), ("BLOCKED", "TARGET_DIRTY"))
        expect("spec-driven is not blocked", derive(repo, mode="spec-driven")["next_action"], "PLAN")


def test_guard_only_when_something_would_be_frozen():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", human_test("humanB"))
        repo.change_target()
        repo.commit("fresh change", days_ago=1)
        expect("a fresh target with gates met is DONE, not BLOCKED", derive(repo)["next_action"], "DONE")
        state = derive(repo, FakeRunner(tests=failing("com.acme.OrderServiceTest#humanB")))
        expect("RED wins over the guard", state["next_action"], "RED")


def test_dirty_stale_green_is_not_resealed():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", ai_test("shouldA", repo.sha()))
        repo.commit("tests", days_ago=20)
        repo.change_target()
        state = derive(repo)
        expect("stale because dirty", state["tests"]["stale"], ["OrderServiceTest#shouldA"])
        expect("no sha to reseal to", state["reseal"], [])
        expect("DONE (nothing would be frozen)", state["next_action"], "DONE")


def test_metadata_defects_are_reported():
    with FixtureRepo() as repo:
        bad = "    /**\n     * tc-agent: generated\n     * tc-agent-mode: legacy\n     */\n    @Test\n    void shouldA() { }\n"
        repo.write_test("OrderServiceTest", bad)
        repo.commit("tests", days_ago=20)
        state = derive(repo)
        expect_true("defect surfaces", any("without tc-agent-characterizes" in d
                                           for d in state["tests"]["metadata_defects"]))


def test_written_file():
    with FixtureRepo() as repo:
        directory = repo.root / ".test-agent" / "runs" / "OrderService" / "r1"
        directory.mkdir(parents=True)
        state = derive(repo)
        path = ds.write(directory, state)
        payload, text = load_payload(path)
        expect("derive-state.md round-trips", payload["next_action"], "PLAN")
        expect_true("human summary on top", "next_action: **PLAN**" in text)


if __name__ == "__main__":
    sys.exit(run_all(globals(), "DERIVE_STATE_OK"))
