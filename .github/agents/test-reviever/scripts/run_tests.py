#!/usr/bin/env python3
"""Compile and run the generated tests, collecting JaCoCo execution data.

This is the ONLY check script that builds the project. It always attaches the
JaCoCo agent, so coverage.py can report from the resulting jacoco.exec without
running the tests a second time.

Usage:
  python run_tests.py <TargetSlug> --repo . [--module M] [--iteration 1]
                      [--repeat 2] [--tests A,B] [--no-existing]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import _common as c

COMPILER_ERROR = re.compile(r"^\[ERROR\]\s+(.+?\.java):\[(\d+),(\d+)\]\s+(.*)$", re.M)
ASSERTION_MARKERS = (
    "assert",
    "opentest4j",
    "comparisonfailure",
    "mockito.exceptions.verification",
)


def failure_phase(failure_type: str) -> str:
    """assertion = the test reached its check and disagreed; setup = it never got there."""
    lowered = (failure_type or "").lower()
    return "assertion" if any(marker in lowered for marker in ASSERTION_MARKERS) else "setup"


def parse_surefire(reports: Path) -> list:
    results = []
    if not reports.exists():
        return results
    for xml in sorted(reports.glob("TEST-*.xml")):
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        for case in root.iter("testcase"):
            klass = case.get("classname", "")
            name = case.get("name", "")
            entry = {"test": f"{klass}#{name}", "status": "PASSED"}
            for tag, status in (("failure", "FAILED"), ("error", "ERROR"), ("skipped", "SKIPPED")):
                element = case.find(tag)
                if element is None:
                    continue
                entry["status"] = status
                if status != "SKIPPED":
                    failure_type = element.get("type", "")
                    entry["failure_phase"] = failure_phase(failure_type)
                    entry["message"] = ((element.get("message") or failure_type or "").strip())[:400]
                    trace = element.text or ""
                    hit = re.search(
                        r"at %s\.[\w$<>]+\(([\w$]+\.java):(\d+)\)" % re.escape(klass), trace
                    )
                    if hit:
                        entry["location"] = f"{hit.group(1)}:{hit.group(2)}"
                break
            results.append(entry)
    return results


def failed_ids(results: list) -> set:
    return {r["test"] for r in results if r["status"] in ("FAILED", "ERROR")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    c.add_common_args(parser)
    parser.add_argument("--repeat", type=int, default=1, help="run the suite N times to expose flakiness")
    parser.add_argument("--tests", default=None, help="explicit comma-separated test classes")
    parser.add_argument("--no-existing", action="store_true", help="do not include the plan's existing tests")
    parser.add_argument("--jacoco-version", default=None)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    data = {"status": "NOT_RUN"}
    summary = []

    try:
        _, plan = c.load_plan(repo, args.slug)
        _, report = c.load_report(repo, args.slug, plan.get("plan_version", 1))
        module = c.resolve_module(plan, args.module)
        tests = (
            [t.strip() for t in args.tests.split(",") if t.strip()]
            if args.tests
            else c.test_fqcns(repo, plan, report, with_existing=not args.no_existing)
        )
        if not tests:
            raise c.CheckError("no test classes resolved from the generation report")

        jacoco = c.tool_version(repo, "jacoco", args.jacoco_version)
        reports_dir = c.module_dir(repo, module) / "target" / "surefire-reports"
        command = (
            [c.mvn_executable(), "-B"]
            + c.module_args(module, also_make=True)
            + [
                "-DfailIfNoTests=false",
                "-Dsurefire.failIfNoSpecifiedTests=false",
                f"-Dtest={','.join(tests)}",
                f"org.jacoco:jacoco-maven-plugin:{jacoco}:prepare-agent",
                "test",
            ]
        )

        runs = []
        output = ""
        for _ in range(max(1, args.repeat)):
            shutil.rmtree(reports_dir, ignore_errors=True)
            code, output = c.run(command, repo)
            runs.append(parse_surefire(reports_dir))

        compiler_errors = [
            f"{Path(m.group(1)).name}:{m.group(2)} {m.group(4).strip()}"
            for m in COMPILER_ERROR.finditer(output)
        ][:20]
        results = runs[0]

        if compiler_errors or ("COMPILATION ERROR" in output and not results):
            data = {
                "status": "COMPILE_ERROR",
                "tests": tests,
                "compiler_errors": compiler_errors or ["compilation failed; see maven output"],
            }
            summary = [f"compilation failed ({len(data['compiler_errors'])} errors)"]
            return c.finish(repo, args.slug, f"tests-r{args.iteration}.md",
                            "Check: tests", summary, data, 1)

        if not results:
            raise c.CheckError(
                "no surefire reports produced; maven exited %s. Tail:\n%s" % (code, output[-1500:])
            )

        flaky = sorted(set().union(*(failed_ids(r) for r in runs)) - set.intersection(*(failed_ids(r) for r in runs))) if len(runs) > 1 else []
        failures = [r for r in results if r["status"] in ("FAILED", "ERROR")]
        data = {
            "status": "FAILED" if failures else "PASSED",
            "tests": tests,
            "runs": len(runs),
            "total": len(results),
            "failed": len(failures),
            "skipped": sum(1 for r in results if r["status"] == "SKIPPED"),
            "failures": failures,
            "flaky": flaky,
        }
        summary = [
            f"{data['total']} tests, {data['failed']} failed, {data['skipped']} skipped",
            f"flaky across {len(runs)} runs: {', '.join(flaky) if flaky else 'none'}",
        ]
        if failures:
            phases = {f.get("failure_phase") for f in failures}
            summary.append("failure phases: " + ", ".join(sorted(p for p in phases if p)))
        code = 1 if (failures or flaky) else 0
        return c.finish(repo, args.slug, f"tests-r{args.iteration}.md",
                        "Check: tests", summary, data, code)

    except c.CheckError as exc:
        data = {"status": "UNAVAILABLE", "reason": str(exc)}
        c.finish(repo, args.slug, f"tests-r{args.iteration}.md",
                 "Check: tests", [str(exc)[:300]], data, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())