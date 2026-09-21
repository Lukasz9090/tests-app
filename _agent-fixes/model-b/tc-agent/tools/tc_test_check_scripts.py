#!/usr/bin/env python3
"""Plumbing tests for the maven-driven check scripts — DEV TOOL, not runtime.

tc_run_tests.py, tc_coverage.py and tc_mutation.py no longer read a plan: they
resolve the target from the slug, discover the test classes that exercise it
and write into the run directory. This drives them for real — through
`tc_orchestrate.py start`, which runs derive-state, which runs the scripts —
against a fixture git repository, with a fake `mvn` (tools/fake_mvn/mvn) that
writes the reports real Maven would write.

What it proves: argument building (-Dtest from discovery, exec file per label,
pit target class), report discovery and parsing, exit codes, and that
derive-state turns them into the right verdict. What it cannot prove: that a
real JDK, JaCoCo and PIT work in your environment — tc_smoke_pipeline.py does
that on a real target.

Usage:
    python .github/agents/tc-agent/tools/tc_test_check_scripts.py [--verbose]
Exit codes: 0 all passed, 1 a case failed, 2 the harness could not run.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from tc_testkit import TC, FixtureRepo, ai_test, expect, expect_true, human_test, run_all  # noqa: E402
    import tc_common as c  # noqa: E402
    from tc_md_payload import load_payload  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)

FAKE = Path(__file__).resolve().parent / "fake_mvn"
ORCH = TC / "scripts" / "tc_orchestrate.py"


def start(repo: FixtureRepo, env: dict | None = None, *extra) -> dict:
    mvn = FAKE / "mvn"
    mvn.chmod(mvn.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log = repo.root / "mvn.log"
    full_env = {**os.environ, "PATH": f"{FAKE}{os.pathsep}{os.environ['PATH']}",
                "FAKE_MVN_LOG": str(log), **(env or {})}
    proc = subprocess.run([sys.executable, str(ORCH), "start", "OrderService", "--repo", str(repo.root),
                           "--mode", "legacy", *extra], capture_output=True, text=True, env=full_env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    out = json.loads(proc.stdout)
    out["dir"] = repo.root / out["run_dir"]
    out["state"] = load_payload(out["dir"] / "derive-state.md")[0]
    out["mvn"] = log.read_text().splitlines() if log.exists() else []
    return out


def fixture() -> FixtureRepo:
    repo = FixtureRepo()
    repo.write_test("OrderServiceTest", ai_test("shouldA", repo.sha()), human_test("humanB"),
                    ai_test("shouldC", repo.sha(), deferred="needs a Clock seam"))
    repo.write_test("UnrelatedTest", human_test("x"))
    repo.commit("tests", days_ago=20)
    return repo


def test_green_run_is_done_through_all_three_scripts():
    with fixture() as repo:
        out = start(repo)
        state = out["state"]
        expect("DONE", (state["next_action"], state["reasons"]), ("DONE", ["GATES_MET"]))
        expect("three maven calls", len(out["mvn"]), 3)
        expect_true("-Dtest is the discovered class only", "-Dtest=OrderServiceTest " in out["mvn"][0] + " ")
        expect_true("exec file is per label", "jacoco-entry.exec" in out["mvn"][0])
        expect_true("coverage reads that exec", "jacoco-entry.exec" in out["mvn"][1])
        expect_true("PIT targets the target class", "-Dpit.targetClasses=com.acme.OrderService" in out["mvn"][2])
        checks = sorted(p.name for p in (out["dir"] / "checks").glob("*.md"))
        expect("reports in the run directory", checks,
               ["coverage-entry.md", "mutation-entry.md", "tests-entry.md"])
        tests = load_payload(out["dir"] / "checks" / "tests-entry.md")[0]
        expect("placeholder counted as skipped", (tests["total"], tests["skipped"]), (3, 1))


def test_failing_human_test_is_red():
    with fixture() as repo:
        out = start(repo, {"FAKE_MVN_FAIL": "OrderServiceTest#humanB"})
        state = out["state"]
        expect("RED", state["next_action"], "RED")
        expect_true("location carried", state["red"][0]["location"].startswith("OrderServiceTest.java:"))


def test_compile_error_is_red():
    with fixture() as repo:
        out = start(repo, {"FAKE_MVN_COMPILE": "cannot find symbol"})
        expect("RED / COMPILE_ERROR", (out["state"]["next_action"], out["state"]["reasons"]),
               ("RED", ["COMPILE_ERROR"]))


def test_coverage_gap_plans_with_lines():
    with fixture() as repo:
        out = start(repo, {"FAKE_MVN_BRANCH": "1,3"})
        state = out["state"]
        expect("PLAN / COVERAGE_GAP", (state["next_action"], state["reasons"]), ("PLAN", ["COVERAGE_GAP"]))
        expect("uncovered line of the if", [u["line"] for u in state["coverage"]["uncovered"]], [5])
        expect("PIT not run", len(out["mvn"]), 2)


def test_mutation_gap_plans():
    with fixture() as repo:
        out = start(repo, {"FAKE_MVN_MUTANTS": "1,3"})
        expect("PLAN / MUTATION_GAP", (out["state"]["next_action"], out["state"]["reasons"]),
               ("PLAN", ["MUTATION_GAP"]))
        expect("survivors", len(out["state"]["mutation"]["survivors"]), 3)


def test_stale_and_failing_goes_to_planner_then_reseal_path():
    with fixture() as repo:
        repo.change_target("return amount * 2;")
        repo.commit("behaviour change", days_ago=10)
        out = start(repo, {"FAKE_MVN_FAIL": "OrderServiceTest#shouldA"})
        state = out["state"]
        expect("PLAN / STALE (placeholder too)", (state["next_action"], state["reasons"]), ("PLAN", ["STALE"]))
        expect("recharacterize", sorted(r["method"] for r in state["recharacterize"]),
               ["OrderServiceTest#shouldA", "OrderServiceTest#shouldC"])
        out2 = start(repo)
        expect("green again -> reseal list", [r["method"] for r in out2["state"]["reseal"]],
               ["OrderServiceTest#shouldA"])


def test_reviewer_label():
    """The Reviewer calls the same scripts with its own label; nothing collides."""
    with fixture() as repo:
        out = start(repo)
        env = {**os.environ, "PATH": f"{FAKE}{os.pathsep}{os.environ['PATH']}"}
        for script in ("tc_run_tests.py", "tc_coverage.py", "tc_mutation.py"):
            proc = subprocess.run([sys.executable, str(TC / "scripts" / script), "OrderService",
                                   "--repo", str(repo.root), "--run", out["run_id"], "--label", "v1-r1"],
                                  capture_output=True, text=True, env=env)
            expect(f"{script} exit 0", proc.returncode, 0)
        names = sorted(p.name for p in (out["dir"] / "checks").glob("*-v1-r1.md"))
        expect("reviewer reports next to the entry ones", names,
               ["coverage-v1-r1.md", "mutation-v1-r1.md", "tests-v1-r1.md"])


def test_missing_run_is_exit_2():
    with fixture() as repo:
        proc = subprocess.run([sys.executable, str(TC / "scripts" / "tc_coverage.py"), "OrderService",
                               "--repo", str(repo.root), "--run", "nope"], capture_output=True, text=True)
        expect("exit 2", proc.returncode, 2)
        expect_true("says why", "not found" in proc.stderr)


if __name__ == "__main__":
    sys.exit(run_all(globals(), "CHECK_SCRIPTS_OK"))
