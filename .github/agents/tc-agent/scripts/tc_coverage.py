#!/usr/bin/env python3
"""Report JaCoCo coverage for the target scope from the exec file tc_run_tests.py wrote.

Invokes the report goal directly, so nothing is compiled and no test is re-run.
Emits the concrete uncovered lines/branches, which is what the Reviewer's
attribution rule and the Planner's gap list consume - the percentage alone is
not actionable. The scope is the class, or the method when the slug names one.

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
    """JaCoCo gives a method's first line only; a method spans up to the next one."""
    methods = sorted(
        ((int(m.get("line", 0)), m) for m in klass.findall("method") if m.get("line")),
        key=lambda pair: pair[0],
    )
    ranges = []
    for index, (line, element) in enumerate(methods):
        if element.get("name") != method_name:
            continue
        end = methods[index + 1][0] - 1 if index + 1 < len(methods) else 10**9
        ranges.append((line, end, element))
    return ranges


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

        # dataFile HAS a user property, outputDirectory does NOT (it defaults to
        # ${project.reporting.outputDirectory}/jacoco and cannot be set from the CLI),
        # so the exec file is pinned and the report is discovered afterwards.
        command = (
            [c.mvn_executable(), "-B"]
            + c.module_args(module)
            + [
                f"org.jacoco:jacoco-maven-plugin:{jacoco}:report",
                f"-Djacoco.dataFile={exec_file}",
            ]
        )
        started = time.time() - 2
        code, output = c.run(command, repo)
        log = c.write_log(directory, f"coverage-{args.label}", command, output)
        notes = []

        # The agent version may come from the pom (it runs during the build), but the
        # REPORT must also be able to ANALYZE the class files. A newer JaCoCo reads an
        # older exec file fine, so one retry with the agent default beats failing.
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
            code, output = c.run(command, repo)
            log = c.write_log(directory, f"coverage-{args.label}", command, output)
            jacoco = newest

        produced = c.recent_files(c.module_dir(repo, module), "**/jacoco.xml", started)
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
            spans = [(start, end) for start, end, _ in ranges]
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
            "uncovered": uncovered[:60],
            "jacoco_version": jacoco,
        }
        if notes:
            data["notes"] = notes
        summary = [
            f"{scope}: branch {branch_ratio:.0%}, line {line_ratio:.0%} (gate {gate:.0%})",
            f"uncovered lines: {', '.join(str(u['line']) for u in uncovered[:12]) or 'none'}",
        ] + notes
        if passed:
            log.unlink(missing_ok=True)   # keep the maven log only for a non-green check
        return c.finish(directory, name, "Check: coverage", summary, data, 0 if passed else 1)

    except c.CheckError as exc:
        if directory is not None:
            c.finish(directory, name, "Check: coverage",
                     [str(exc)[:300]], {"status": "UNAVAILABLE", "reason": str(exc)}, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())