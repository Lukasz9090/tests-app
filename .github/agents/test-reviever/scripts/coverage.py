#!/usr/bin/env python3
"""Report JaCoCo coverage for the plan's target scope from an existing jacoco.exec.

Invokes the report goal directly, so nothing is compiled and no test is re-run.
Emits the concrete uncovered lines/branches, which is what the Reviewer's
attribution rule consumes - the percentage alone is not actionable.

Usage:
  python coverage.py <TargetSlug> --repo . [--module M] [--iteration 1] [--gate 0.8]
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import _common as c

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

    repo = Path(args.repo).resolve()
    name = f"coverage-r{args.iteration}.md"

    try:
        _, plan = c.load_plan(repo, args.slug)
        module = c.resolve_module(plan, args.module)
        fqcn, _ = c.target_fqcn(repo, plan)
        _, method = c.target_scope(plan)
        gate = c.gate_value(repo, GATE_KEY, args.gate)
        jacoco = c.tool_version(repo, "jacoco", args.jacoco_version)

        exec_file = c.module_dir(repo, module) / "target" / "jacoco.exec"
        if not exec_file.exists():
            raise c.CheckError(f"{exec_file} not found - run run_tests.py first")

        code, output = c.run(
            [c.mvn_executable(), "-B"]
            + c.module_args(module)
            + [f"org.jacoco:jacoco-maven-plugin:{jacoco}:report"],
            repo,
        )
        xml_path = c.module_dir(repo, module) / "target" / "site" / "jacoco" / "jacoco.xml"
        if not xml_path.exists():
            raise c.CheckError(
                "jacoco.xml not produced (maven exit %s). Tail:\n%s" % (code, output[-1200:])
            )

        root = ET.parse(xml_path).getroot()
        package, klass = find_class(root, fqcn)
        if klass is None:
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
            "uncovered": uncovered[:60],
        }
        summary = [
            f"{scope}: branch {branch_ratio:.0%}, line {line_ratio:.0%} (gate {gate:.0%})",
            f"uncovered lines: {', '.join(str(u['line']) for u in uncovered[:12]) or 'none'}",
        ]
        return c.finish(repo, args.slug, name, "Check: coverage", summary, data, 0 if passed else 1)

    except c.CheckError as exc:
        c.finish(repo, args.slug, name, "Check: coverage",
                 [str(exc)[:300]], {"status": "UNAVAILABLE", "reason": str(exc)}, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())