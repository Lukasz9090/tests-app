#!/usr/bin/env python3
"""Run PIT on the target class only and report the surviving mutants.

Invokes the mutationCoverage goal directly: nothing is compiled here, PIT reuses
the classes built by tc_run_tests.py and drives the tests itself.

Usage:
  python tc_mutation.py <TargetSlug> --repo . [--module M] [--iteration 1]
                     [--gate 0.7]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import tc_common as c

GATE_KEY = "mutation_score_target_scope"
KILLED = {"KILLED", "TIMED_OUT", "MEMORY_ERROR"}
# Matched against the EXTRACTED error only, never the whole log: PIT prints its
# plugin inventory on every run ("Detect missing JUnit5 plugin", "Adding
# org.pitest:pitest-junit5-plugin to SUT classpath"), so scanning the full output
# diagnoses a missing junit5 plugin on runs that have one.
UNAVAILABLE_MARKERS = (
    "no test framework",
    "unknown test framework",
    "unable to determine test framework",
    "missing junit5 plugin",
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
    parser.add_argument("--tests", default=None, help="explicit comma-separated test classes")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    name = f"mutation-r{args.iteration}.md"

    try:
        _, plan = c.load_plan(repo, args.slug)
        _, report = c.load_report(repo, args.slug, plan.get("plan_version", 1))
        fqcn, target_file = c.target_fqcn(repo, plan)
        module = c.resolve_module(repo, plan, args.module, target_file)
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

        command = (
            [c.mvn_executable(), "-B"]
            + c.module_args(module)
            + [
                f"org.pitest:pitest-maven:{pit}:mutationCoverage",
                # both spellings: bare properties work when the pom leaves targetClasses
                # unset, the pit.* ones when the pom uses ${pit.targetClasses} indirection.
                # A literal value inside <configuration> always wins over -D, so a pom that
                # hardcodes a package makes narrow scoping impossible - reported below.
                f"-DtargetClasses={fqcn}",
                f"-DtargetTests={','.join(tests)}",
                f"-Dpit.targetClasses={fqcn}",
                f"-Dpit.targetTests={','.join(tests)}",
                "-DoutputFormats=XML",
                "-DtimestampedReports=false",
            ]
        )

        started = time.time() - 2
        code, output = c.run(command, repo)
        log = c.write_log(repo, args.slug, f"mutation-r{args.iteration}", command, output)
        found = c.recent_files(c.module_dir(repo, module), "**/mutations.xml", started)
        xml_path = found[-1] if found else c.module_dir(repo, module) / "target" / "pit-reports" / "mutations.xml"

        if not found:
            failure = c.maven_error(output)
            lowered = failure.lower()
            if xml_path.parent.exists():
                reason = (
                    f"pit-reports exists but mutations.xml does not - add XML to <outputFormats> "
                    f"in the pom (a literal value there overrides -DoutputFormats); full log: {log}"
                )
                c.finish(repo, args.slug, name, "Check: mutation",
                         [reason[:300]], {"status": "SKIPPED_UNAVAILABLE", "reason": reason}, 2)
                return c.fail(reason)
            if any(marker in lowered for marker in UNAVAILABLE_MARKERS):
                reason = (
                    "PIT could not run the tests - with JUnit 5 the pitest-junit5-plugin "
                    "must be declared as a plugin dependency in the pom (it cannot be added "
                    f"from the CLI); full log: {log}"
                )
            else:
                reason = "mutations.xml not produced (maven exit %s, full log: %s):\n%s" % (
                    code, log, failure)
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
        if passed:
            log.unlink(missing_ok=True)   # keep the maven log only for a non-green check
        return c.finish(repo, args.slug, name, "Check: mutation", summary, data, 0 if passed else 1)

    except c.CheckError as exc:
        c.finish(repo, args.slug, name, "Check: mutation",
                 [str(exc)[:300]], {"status": "SKIPPED_UNAVAILABLE", "reason": str(exc)}, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())