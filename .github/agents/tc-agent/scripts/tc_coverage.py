#!/usr/bin/env python3
"""Reports JaCoCo branch coverage of the target (class or method) from the run's exec file,
with the uncovered lines and the per-method line counters.

Usage:
  python tc_coverage.py <TargetSlug> --repo . --run <id|latest> [--label entry]
                     [--module M] [--gate 0.8]
Output:
  <run>/checks/coverage-<label>.md
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import tc_common as c

GATE_KEY = "branch_coverage_target_scope"


def counters(element) -> dict:
    out = {}
    for counter in element.findall("counter"):
        out[counter.get("type")] = (
            int(counter.get("missed", 0)),
            int(counter.get("covered", 0)),
        )
    return out


def ratio(pair) -> float:
    missed, covered = pair
    total = missed + covered
    return round(covered / total, 4) if total else 1.0


def find_class(root, fqcn: str):
    wanted = fqcn.replace(".", "/")
    for package in root.findall("package"):
        for klass in package.findall("class"):
            if klass.get("name") == wanted:
                return package, klass
    return None, None


def method_ranges(klass, method_name: str) -> list:
    """(first, last, element) per overload of the method, plus its lambdas as (0, 0, element)."""
    methods = sorted(
        ((int(m.get("line", 0)), m) for m in klass.findall("method")
         if m.get("line") and "$" not in m.get("name", "")),
        key=lambda pair: pair[0],
    )
    ranges = []
    for index, (line, element) in enumerate(methods):
        if element.get("name") != method_name:
            continue
        end = methods[index + 1][0] - 1 if index + 1 < len(methods) else 10**9
        ranges.append((line, end, element))
    lambdas = [(0, 0, m) for m in klass.findall("method")
               if m.get("name", "").startswith(f"lambda${method_name}$")]
    return ranges + lambdas if ranges else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    c.add_common_args(parser)
    parser.add_argument("--gate", type=float, default=None)
    parser.add_argument("--jacoco-version", default=None)
    args = parser.parse_args()

    name = f"coverage-{args.label}.md"
    directory = None

    try:
        repo, directory, target = c.open_run(args)
        fqcn, module, method = target.fqcn, target.module, target.method
        gate = c.gate_value(repo, GATE_KEY, args.gate)
        jacoco = c.tool_version(repo, "jacoco", args.jacoco_version, module)

        exec_file = c.checks_dir(directory) / f"jacoco-{args.label}.exec"
        if not exec_file.exists():
            raise c.CheckError(f"{exec_file} not found - run tc_run_tests.py first")
        if exec_file.stat().st_size == 0:
            raise c.CheckError(
                f"{exec_file} is empty - the tests ran without the JaCoCo agent, so any report "
                "would be empty too; re-run tc_run_tests.py and read its diagnosis"
            )

        # The tests check usually wrote the report already; maven runs only when it did not.
        reused = None
        tests_payload = c.checks_dir(directory) / f"tests-{args.label}.md"
        if tests_payload.exists():
            try:
                told = c.payload(tests_payload).get("jacoco_xml")
            except c.CheckError:
                told = None
            if told and Path(told).is_file() and Path(told).stat().st_mtime >= exec_file.stat().st_mtime:
                reused = Path(told)

        # dataFile has a user property, outputDirectory does not: the report is found afterwards.
        command = (
            c.mvn_base(repo)
            + c.module_args(module)
            + [
                f"org.jacoco:jacoco-maven-plugin:{jacoco}:report",
                f"-Djacoco.dataFile={exec_file}",
            ]
        )
        log = c.checks_dir(directory) / f"maven-coverage-{args.label}.log"
        notes = []
        maven_seconds = 0.0
        code, output, started = 0, "", time.time() - 2
        if reused is None:
            clock = time.time()
            code, output = c.run(command, repo, timeout=c.maven_timeout(repo), log_path=log)
            maven_seconds = time.time() - clock
        else:
            notes.append("report reused from the tests check - maven was not started")
            print(f"[tc-agent] reusing the jacoco report written by the tests check ({reused})",
                  file=sys.stderr, flush=True)

        # A report that cannot read the class files is retried with the agent default.
        newest = c.DEFAULT_VERSIONS["jacoco"]
        if (
            code != 0
            and "unsupported class file major version" in output.lower()
            and jacoco != newest
        ):
            notes.append(f"retried report with {newest}: {jacoco} cannot analyze these class files")
            command = [
                f"org.jacoco:jacoco-maven-plugin:{newest}:report" if "jacoco-maven-plugin" in part
                else part
                for part in command
            ]
            started = time.time() - 2
            clock = time.time()
            code, output = c.run(command, repo, timeout=c.maven_timeout(repo), log_path=log)
            maven_seconds += time.time() - clock
            jacoco = newest

        if reused is not None:
            xml_path = reused
        else:
            produced = c.recent_files(c.module_dir(repo, module), "**/jacoco.xml", started,
                                      prefer=("target/site/jacoco/jacoco.xml",))
            xml_path = produced[-1] if produced else None
        if code != 0:
            raise c.CheckError(
                "jacoco:report failed (maven exit %s, full log: %s):\n%s"
                % (code, log, c.maven_error(output))
            )
        if xml_path is None:
            raise c.CheckError(
                "no jacoco.xml written under %s by this run - check that XML is among the "
                "report formats configured for the plugin. Full log: %s\n%s"
                % (c.module_dir(repo, module), log, c.maven_error(output))
            )

        root = c.parse_xml(xml_path)
        package, klass = find_class(root, fqcn)
        if klass is None:
            if not root.findall("package"):
                raise c.CheckError(
                    f"{xml_path} contains no packages - the report has no execution data "
                    "(agent not attached, or the exec file belongs to another module)"
                )
            raise c.CheckError(f"{fqcn} absent from jacoco.xml - wrong module or class never loaded")

        scope = f"{fqcn}.{method}" if method else fqcn
        if method:
            ranges = method_ranges(klass, method)
            if not ranges:
                raise c.CheckError(f"method {method} not found in {fqcn}")
            branch = [0, 0]
            line = [0, 0]
            for _, _, element in ranges:
                found = counters(element)
                for key, acc in (("BRANCH", branch), ("LINE", line)):
                    missed, covered = found.get(key, (0, 0))
                    acc[0] += missed
                    acc[1] += covered
            spans = [(start, end) for start, end, _ in ranges if end]
        else:
            found = counters(klass)
            branch = list(found.get("BRANCH", (0, 0)))
            line = list(found.get("LINE", (0, 0)))
            spans = [(0, 10**9)]

        source = None
        for candidate in package.findall("sourcefile"):
            if candidate.get("name") == klass.get("sourcefilename"):
                source = candidate
                break

        uncovered = []
        if source is not None:
            for entry in source.findall("line"):
                number = int(entry.get("nr"))
                if not any(start <= number <= end for start, end in spans):
                    continue
                missed_branches = int(entry.get("mb", 0))
                missed_instructions = int(entry.get("mi", 0))
                covered_instructions = int(entry.get("ci", 0))
                if missed_branches or (missed_instructions and not covered_instructions):
                    item = {"line": number, "missed_branches": missed_branches}
                    if method:
                        item["method"] = method
                    uncovered.append(item)

        # Per-method line counters: a method no test executes at all (typically
        # one just added) must be visible even when the class-level gate passes.
        methods = []
        for element in klass.findall("method"):
            mname = element.get("name", "")
            if mname in ("<clinit>",) or mname.startswith("lambda$") or "$" in mname:
                continue
            if method and mname != method:
                continue
            missed, covered = counters(element).get("LINE", (0, 0))
            methods.append({"name": mname, "line": int(element.get("line", 0) or 0),
                            "line_missed": missed, "line_covered": covered})

        branch_ratio = ratio(tuple(branch))
        line_ratio = ratio(tuple(line))
        measured = branch_ratio if sum(branch) else line_ratio
        passed = measured >= gate

        data = {
            "status": "PASSED" if passed else "FAILED",
            "scope": scope,
            "branch_ratio": branch_ratio,
            "line_ratio": line_ratio,
            "gate": gate,
            "gated_on": "branch" if sum(branch) else "line",
            "report": str(xml_path),
            "uncovered": uncovered[:200],
            "methods": methods,
            "jacoco_version": jacoco,
            "maven_seconds": round(maven_seconds, 1),
        }
        if notes:
            data["notes"] = notes
        summary = [
            f"{scope}: branch {branch_ratio:.0%}, line {line_ratio:.0%} (gate {gate:.0%})",
            f"uncovered lines: {', '.join(str(u['line']) for u in uncovered[:12]) or 'none'}",
            (f"maven took {round(maven_seconds)}s (report only - no tests are re-run)"
             if reused is None else "no maven call - the tests check already wrote the report"),
        ] + notes
        if passed:
            c.trim_log(log)   # a green check keeps only the tail of its maven log
        return c.finish(directory, name, "Check: coverage", summary, data, 0 if passed else 1)

    except c.CheckError as exc:
        if directory is not None:
            c.finish(directory, name, "Check: coverage",
                     [str(exc)[:300]], {"status": "UNAVAILABLE", "reason": str(exc)}, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())