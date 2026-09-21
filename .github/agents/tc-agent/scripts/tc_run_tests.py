#!/usr/bin/env python3
"""Compile and run every test class that exercises the target, collecting JaCoCo data.

This is the ONLY check script that builds the project. It makes sure the JaCoCo
agent is attached exactly ONCE - injected as a fully-qualified goal only when the
pom does not already bind prepare-agent - so tc_coverage.py can report from the
resulting exec file without running the tests a second time.

The test classes are discovered from the target (tc_common.discover_test_classes):
human and AI tests alike, no plan or report needed. That is what lets
derive-state run it before anything was planned.

Usage:
  python tc_run_tests.py <TargetSlug> --repo . --run <id|latest> [--label entry]
                      [--module M] [--repeat 2] [--tests A,B]
Output:
  <run>/checks/tests-<label>.md, <run>/checks/jacoco-<label>.exec
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import tc_common as c

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


def parse_surefire(report_files) -> list:
    results = []
    for xml in report_files:
        try:
            root = c.parse_xml(xml)
        except (c.CheckError, ET.ParseError):
            continue  # one unreadable surefire file must not sink the whole check
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
    parser.add_argument("--tests", default=None, help="explicit comma-separated test classes (overrides discovery)")
    parser.add_argument("--jacoco-version", default=None)
    args = parser.parse_args()

    name = f"tests-{args.label}.md"
    directory = None

    try:
        repo, directory, target = c.open_run(args)
        module = target.module
        tests = (
            [t.strip() for t in args.tests.split(",") if t.strip()]
            if args.tests
            else [fqcn for fqcn, _ in c.discover_test_classes(repo, target)]
        )
        if not tests:
            raise c.CheckError(f"no test class exercises {target.cls} - nothing to run")

        jacoco = c.tool_version(repo, "jacoco", args.jacoco_version, module)
        search_root = c.module_dir(repo, module)
        # Pin the exec file instead of hunting for it: -Djacoco.destFile works for
        # a pom-bound execution too, so both invocation modes land in one known place.
        exec_file = c.checks_dir(directory) / f"jacoco-{args.label}.exec"
        # surefire matches -Dtest most reliably on simple class names; PIT gets the FQCNs
        selectors = sorted({name.split(".")[-1] for name in tests})
        bound_pom = c.pom_binds_jacoco_agent(repo, module)
        agent_goal = [] if bound_pom else [f"org.jacoco:jacoco-maven-plugin:{jacoco}:prepare-agent"]
        agent_source = f"pom-bound ({bound_pom})" if bound_pom else f"cli goal ({jacoco})"
        command = (
            [c.mvn_executable(), "-B"]
            + c.module_args(module, also_make=True)
            + [
                "-DfailIfNoTests=false",
                "-Dsurefire.failIfNoSpecifiedTests=false",
                f"-Dtest={','.join(selectors)}",
                f"-Djacoco.destFile={exec_file}",
            ]
            + agent_goal
            + ["test"]
        )

        runs = []
        output = ""
        report_files = []
        for _ in range(max(1, args.repeat)):
            started = time.time() - 2  # filesystem mtime granularity slack
            exec_file.unlink(missing_ok=True)
            code, output = c.run(command, repo)
            report_files = c.recent_files(search_root, "target/surefire-reports/TEST-*.xml", started)
            runs.append(parse_surefire(report_files))
        log = c.write_log(directory, f"tests-{args.label}", command, output)

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
            return c.finish(directory, name, "Check: tests", summary, data, 1)

        if not results:
            raise c.CheckError(
                "no surefire reports written under %s (maven exited %s). In a multi-module "
                "repo the reports live in <module>/target - resolved module: %s. Full log: %s\n%s"
                % (search_root, code, module or "(repo root)", log, c.maven_error(output))
            )

        executed = sum(1 for r in results if r["status"] != "SKIPPED")
        if not executed:
            raise c.CheckError(
                f"surefire ran 0 tests for -Dtest={','.join(selectors)} - check the "
                f"discovered class names and the module ({module or 'root'}); "
                f"full log: {log}"
            )
        if not exec_file.exists() or exec_file.stat().st_size == 0:
            pom = c.hardcoded_arg_line(repo, module)
            hint = (
                f"{pom} pins surefire <argLine> without @{{argLine}}, which overrides the "
                "property prepare-agent sets - the tests ran WITHOUT the JaCoCo agent. Fix the "
                "pom: <argLine>@{argLine} ...</argLine>"
                if pom
                else f"agent source was {agent_source}; if pom-bound, its execution may sit in an "
                f"inactive profile. Expected exec at {exec_file}"
            )
            raise c.CheckError(f"{executed} tests ran but {exec_file.name} is missing/empty. {hint}")

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
            "jacoco_agent": agent_source,
            "module": module,
            "label": args.label,
            "exec_file": str(exec_file),
            "report_files": [str(f) for f in report_files],
        }
        summary = [
            f"{data['total']} tests, {data['failed']} failed, {data['skipped']} skipped",
            f"flaky across {len(runs)} runs: {', '.join(flaky) if flaky else 'none'}",
            f"jacoco agent: {agent_source}",
        ]
        if failures:
            phases = {f.get("failure_phase") for f in failures}
            summary.append("failure phases: " + ", ".join(sorted(p for p in phases if p)))
        code = 1 if (failures or flaky) else 0
        if code == 0:
            log.unlink(missing_ok=True)   # keep the maven log only for a non-green check
        return c.finish(directory, name, "Check: tests", summary, data, code)

    except c.CheckError as exc:
        data = {"status": "UNAVAILABLE", "reason": str(exc)}
        if directory is not None:
            c.finish(directory, name, "Check: tests", [str(exc)[:300]], data, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())