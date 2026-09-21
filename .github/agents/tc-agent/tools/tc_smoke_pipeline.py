#!/usr/bin/env python3
"""End-to-end smoke test of the maven-driven check scripts — DEV TOOL, not runtime.

The unit tests (tc_test_*.py) run without maven; tc_test_check_scripts.py even
drives the three check scripts through a fake `mvn`. None of that proves the
real toolchain works here: the JDK, the JaCoCo agent attached exactly once, PIT
finding its JUnit 5 plugin. Their failure mode is exit code 2, "the check could
not run", which derive-state and the Reviewer turn into ESCALATE / BLOCKED.

So this tool creates a real run for a real target (`tc_orchestrate.py start`,
spec-driven so the freshness guard stays out of the way), then runs
tc_run_tests.py, tc_coverage.py and tc_mutation.py against it with the label
`smoke`, and asserts that none of them exits 2 and that every report parses.

It does NOT assert that the gates pass: exit 1 is a verdict about the tests,
not a broken pipeline. Exit 2 is the failure this tool exists to catch.

The target needs at least one test class that exercises it (the scripts
discover test classes from the code; there is no plan to name them).

Usage:
    python .github/agents/tc-agent/tools/tc_smoke_pipeline.py [--target SimpleCalculatorService]
                                                             [--repo .] [--skip-mutation] [--keep]

Exit codes:
    0 — every script ran and its report parses
    1 — a script could not run, or wrote a report that does not parse
    2 — the smoke test could not be set up (unknown target, no test class)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
TC = HERE.parents[1]
SCRIPTS = TC / "scripts"
sys.path.insert(0, str(SCRIPTS))

import tc_common as c  # noqa: E402
from tc_md_payload import load_payload  # noqa: E402


def run_script(name: str, repo: Path, target: str, run_id: str, extra: list) -> int:
    command = [sys.executable, str(SCRIPTS / name), target, "--repo", str(repo),
               "--run", run_id, "--label", "smoke", *extra]
    print(f"\n$ {' '.join(command[1:])}", flush=True)
    result = subprocess.run(command, cwd=repo, capture_output=True, text=True)
    for line in (result.stdout + result.stderr).splitlines():
        print(f"  {line}")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", default="SimpleCalculatorService")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--skip-mutation", action="store_true", help="skip PIT, the slowest check")
    parser.add_argument("--keep", action="store_true", help="keep the smoke run directory")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    try:
        target = c.resolve_target(repo, args.target)
    except c.CheckError as exc:
        print(f"CANNOT_RUN: {exc}", file=sys.stderr)
        return 2
    classes = c.discover_test_classes(repo, target)
    if not classes:
        print(f"CANNOT_RUN: no test class exercises {target.cls}; write one first "
              f"(the scripts discover test classes from the code)", file=sys.stderr)
        return 2

    # A run directory only - derive-state is not needed for the smoke, so the
    # run is created directly instead of through `start` (which would build twice).
    root = c.runs_root(repo, args.target)
    run_id = "smoke-" + __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = root / run_id
    directory.mkdir(parents=True)
    c.save_run(directory, {"schema_version": 1, "slug": args.target, "run_id": run_id,
                           "mode": "spec-driven", "interactive": False, "spec": None,
                           "caps": {"impl_cap": 1, "plan_cap": 1}, "commit": False,
                           "started": "smoke", "resealed": False})
    print(f"smoke target: {target.fqcn} (tests: {', '.join(fq for fq, _ in classes)}), run {directory}")

    failures = []
    steps = [("tc_run_tests.py", ["--repeat", "1"], "tests-smoke.md"),
             ("tc_coverage.py", [], "coverage-smoke.md")]
    if not args.skip_mutation:
        steps.append(("tc_mutation.py", [], "mutation-smoke.md"))
    for script, extra, report in steps:
        code = run_script(script, repo, args.target, run_id, extra)
        if code == 2:
            failures.append(f"{script} exited 2 — the check could not run")
        elif code not in (0, 1):
            failures.append(f"{script} exited {code}, which is not a defined code")
        else:
            print(f"  {script} exited {code} (ran)")
        path = directory / "checks" / report
        try:
            data, _ = load_payload(path)
            print(f"  report {report}: status={data.get('status')}")
        except ValueError as exc:
            failures.append(f"{report} missing or unreadable: {exc}")

    if not args.keep:
        shutil.rmtree(directory, ignore_errors=True)

    print()
    if failures:
        print(f"SMOKE_FAILED ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PIPELINE_SMOKE_OK — every check script ran and wrote a readable report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
