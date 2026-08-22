#!/usr/bin/env python3
"""Run PIT on the target class only and report the surviving mutants.

Invokes the mutationCoverage goal directly: nothing is compiled here, PIT reuses
the classes built by run_tests.py and drives the tests itself. A history file is
kept per target so later repair iterations skip unchanged mutants.

Usage:
  python mutation.py <TargetSlug> --repo . [--module M] [--iteration 1]
                     [--gate 0.7] [--provider pit|descartes]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _common as c

GATE_KEY = "mutation_score_target_scope"
KILLED = {"KILLED", "TIMED_OUT", "MEMORY_ERROR"}
UNAVAILABLE_MARKERS = (
    "pitest-junit5-plugin",
    "no test framework",
    "unknown test framework",
    "unable to determine test framework",
    "found 0 tests",
    "no tests found",
)


def text(node, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    c.add_common_args(parser)
    parser.add_argument("--gate", type=float, default=None)
    parser.add_argument("--pit-version", default=None)
    parser.add_argument("--provider", choices=["pit", "descartes"], default="pit")
    parser.add_argument("--tests", default=None, help="explicit comma-separated test classes")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    name = f"mutation-r{args.iteration}.md"

    try:
        _, plan = c.load_plan(repo, args.slug)
        _, report = c.load_report(repo, args.slug, plan.get("plan_version", 1))
        module = c.resolve_module(plan, args.module)
        fqcn, _ = c.target_fqcn(repo, plan)
        _, method = c.target_scope(plan)
        gate = c.gate_value(repo, GATE_KEY, args.gate)
        pit = c.tool_version(repo, "pit", args.pit_version, module)

        tests = (
            [t.strip() for t in args.tests.split(",") if t.strip()]
            if args.tests
            else c.test_fqcns(repo, plan, report)
        )
        if not tests:
            raise c.CheckError("no test classes resolved from the generation report")

        history = c.checks_dir(repo, args.slug) / "pit-history.bin"
        command = (
            [c.mvn_executable(), "-B"]
            + c.module_args(module)
            + [
                f"org.pitest:pitest-maven:{pit}:mutationCoverage",
                f"-DtargetClasses={fqcn}",
                f"-DtargetTests={','.join(tests)}",
                "-DoutputFormats=XML",
                "-DtimestampedReports=false",
                f"-DhistoryInputFile={history}",
                f"-DhistoryOutputFile={history}",
            ]
        )
        if args.provider == "descartes":
            command.append("-Dfeatures=+CLASSLIMIT(limit[1])")
            command.append("-DmutationEngine=descartes")

        code, output = c.run(command, repo)
        xml_path = c.module_dir(repo, module) / "target" / "pit-reports" / "mutations.xml"

        if not xml_path.exists():
            lowered = output.lower()
            if any(marker in lowered for marker in UNAVAILABLE_MARKERS):
                reason = (
                    "PIT could not run the tests - with JUnit 5 the pitest-junit5-plugin "
                    "must be declared as a plugin dependency in the pom (it cannot be added "
                    "from the CLI)"
                )
            else:
                reason = "mutations.xml not produced (maven exit %s):\n%s" % (code, c.maven_error(output))
            c.finish(repo, args.slug, name, "Check: mutation",
                     [reason[:300]], {"status": "SKIPPED_UNAVAILABLE", "reason": reason}, 2)
            return c.fail(reason)

        root = c.parse_xml(xml_path)
        killed = 0
        survivors = []
        total = 0
        for mutation in root.iter("mutation"):
            mutated_class = text(mutation, "mutatedClass")
            mutated_method = text(mutation, "mutatedMethod")
            if not (mutated_class == fqcn or mutated_class.startswith(fqcn + "$")):
                continue
            if method and mutated_method != method:
                continue
            total += 1
            status = (mutation.get("status") or "").upper()
            if status in KILLED:
                killed += 1
            else:
                survivors.append(
                    {
                        "line": int(text(mutation, "lineNumber") or 0),
                        "method": mutated_method,
                        "mutator": text(mutation, "mutator").split(".")[-1],
                        "status": status,
                    }
                )

        scope = f"{fqcn}.{method}" if method else fqcn
        score = round(killed / total, 4) if total else 1.0
        passed = score >= gate
        data = {
            "status": "PASSED" if passed else "FAILED",
            "scope": scope,
            "score": score,
            "gate": gate,
            "killed": killed,
            "survived": sum(1 for s in survivors if s["status"] == "SURVIVED"),
            "no_coverage": sum(1 for s in survivors if s["status"] == "NO_COVERAGE"),
            "survivors": sorted(survivors, key=lambda s: s["line"])[:60],
        }
        if not total:
            data["reason"] = "no mutants generated for this scope"
        summary = [
            f"{scope}: score {score:.0%} of {total} mutants (gate {gate:.0%})",
            "survivors: "
            + (", ".join(f"{s['line']}/{s['mutator']}" for s in data["survivors"][:12]) or "none"),
        ]
        return c.finish(repo, args.slug, name, "Check: mutation", summary, data, 0 if passed else 1)

    except c.CheckError as exc:
        c.finish(repo, args.slug, name, "Check: mutation",
                 [str(exc)[:300]], {"status": "SKIPPED_UNAVAILABLE", "reason": str(exc)}, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())