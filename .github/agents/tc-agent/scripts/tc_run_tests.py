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
  python tc_run_tests.py <target> --repo . --run <id|latest> [--label entry]
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
    parser.add_argument("--repeat", type=int, default=None,
                        help="force N runs; without it, one run plus a confirmation run when "
                             "something failed (profile: flaky_repeat)")
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
        prepare_agent = f"org.jacoco:jacoco-maven-plugin:{jacoco}:prepare-agent"

        # JaCoCo and PIT never have to be configured in the pom: the checks call
        # their goals by full coordinates. prepare-agent is injected ALWAYS,
        # because the alternative is reading the pom and guessing - and a pom
        # whose execution sits in an inactive profile reads as "bound" while no
        # agent ever attaches, which ends as an empty exec file and a dead run.
        # The one thing that can go wrong - a pom-bound execution firing in the
        # `test` phase on top of ours, two -javaagent switches, a forked VM that
        # dies before the first test - is recognisable in the output and costs
        # one retry (`drop_agent`), not a human.
        # ... and once a repo has proved its pom really does bind the agent, the
        # answer is remembered, so the doomed attempt is paid once, not once per
        # round. The hint is disproved by an empty exec file below.
        drop_agent = c.env_hint(repo, "jacoco_agent", module) == "pom"
        if drop_agent:
            print("[tc-agent] this pom bound the JaCoCo agent on an earlier run - leaving "
                  "prepare-agent to it", file=sys.stderr, flush=True)

        def agent_goals(goals: list) -> list:
            return [] if drop_agent else [prepare_agent]
        also_make = c.maven_also_make(repo)

        skip_main = []
        mode = c.maven_skip_main_compile(repo)
        if mode is not False:
            classes = c.built_classes(repo, module)
            if classes is None:
                print("[tc-agent] nothing is compiled under "
                      f"{c.module_dir(repo, module)}/target/classes yet - building src/main this "
                      "once; in a big module this can take minutes.",
                      file=sys.stderr, flush=True)
            else:
                # "auto" asks about the class under test; "strict" about every
                # source in the module. The other answer is still printed, so a
                # decision is never silent about what it ignored.
                mine = c.stale_target(repo, module, classes, target.file)
                anyone = c.stale_classes(repo, module, classes)
                decisive = anyone if mode == "strict" else mine
                if decisive and mode is not True:
                    print(f"[tc-agent] {c.describe_stale(decisive)} - rebuilding src/main so the "
                          "measurement matches the code; in a big module this can take minutes.",
                          file=sys.stderr, flush=True)
                else:
                    if decisive:
                        print(f"[tc-agent] WARNING: {c.describe_stale(decisive)}, and this run "
                              "measures the classes as they are "
                              "(maven_skip_main_compile: true). Run `mvn -DskipTests install` if "
                              "the results look wrong.", file=sys.stderr, flush=True)
                    elif anyone:
                        print(f"[tc-agent] {target.cls} itself is compiled and unchanged, so "
                              "src/main is not rebuilt. Another source in the module is stale "
                              f"({c.describe_stale(anyone)}), which changes nothing here unless "
                              "the tests depend on it - set maven_skip_main_compile: \"strict\" "
                              "to rebuild on that too.", file=sys.stderr, flush=True)
                    else:
                        print("[tc-agent] src/main is already compiled and unchanged - running "
                              "against target/classes", file=sys.stderr, flush=True)
                    skip_main = ["-Dmaven.main.skip=true"]

        # Goals, not the phase: skip every generator and resource plugin bound
        # before `test`. Only possible when src/main is already built.
        lifecycle = c.maven_lifecycle(repo, bool(skip_main))
        goals_only = lifecycle != ["test"]
        if goals_only:
            print("[tc-agent] running the goals directly (%s) - no generators, no node build, "
                  "nothing else the `test` phase would drag in. maven_goals_only: false to run "
                  "the phase." % " ".join(lifecycle), file=sys.stderr, flush=True)

        # The coverage report in the SAME call: the agent has just flushed the exec
        # file when surefire's JVM exited, so the report goal can read it here and
        # tc_coverage.py needs no maven of its own. One maven start less, and in a
        # big reactor that start was 20-40 seconds of the run's budget. It only
        # runs when the tests pass (maven stops at a failed surefire), which is
        # exactly when coverage is worth measuring.
        report_goal = [f"org.jacoco:jacoco-maven-plugin:{jacoco}:report",
                       f"-Djacoco.dataFile={exec_file}"]

        def command_tail(goals: list) -> list:
            return [
                "-DfailIfNoTests=false",
                "-Dsurefire.failIfNoSpecifiedTests=false",
                f"-Dtest={','.join(selectors)}",
                f"-Djacoco.destFile={exec_file}",
                *agent_goals(goals),
                *goals,
                *report_goal,
            ]

        def build_command(with_am: bool, goals: list) -> list:
            return (c.mvn_base(repo) + skip_main
                    + c.module_args(module, also_make=with_am) + command_tail(goals))

        command = build_command(with_am=(also_make is True), goals=lifecycle)
        retried_with_am = False

        runs = []
        output = ""
        report_files = []
        maven_seconds = 0.0
        run_started = time.time() - 2
        log_path = c.checks_dir(directory) / f"maven-tests-{args.label}.log"

        def attempt():
            """One maven call, with the reports it wrote."""
            nonlocal maven_seconds
            started = time.time() - 2  # filesystem mtime granularity slack
            exec_file.unlink(missing_ok=True)
            clock = time.time()
            code, output = c.run(command, repo, timeout=c.maven_timeout(repo), log_path=log_path)
            maven_seconds += time.time() - clock
            files = c.recent_files(search_root, "target/surefire-reports/TEST-*.xml", started,
                                   prefer=("target/surefire-reports/TEST-*.xml",))
            return code, output, files, parse_surefire(files)

        planned = max(1, args.repeat or c.flaky_repeat(repo))
        for _ in range(planned):
            code, output, report_files, results = attempt()
            # "auto": the fast build first; only a repo that has not installed its
            # modules pays for -am, and it is told how to stop paying.
            if (code != 0 and also_make == "auto" and not retried_with_am
                    and c.needs_also_make(output)):
                retried_with_am = True
                command = build_command(with_am=True, goals=lifecycle)
                print("[tc-agent] the module's dependencies are not installed; rebuilding them "
                      "with -am. Run `mvn -DskipTests install` once to skip this.",
                      file=sys.stderr, flush=True)
                code, output, report_files, results = attempt()
            # Two agents on one JVM: ours plus a pom-bound execution that the
            # phase fired. Drop ours and let the pom's do the job.
            if code != 0 and not drop_agent and c.duplicate_agent(output):
                drop_agent = True
                c.save_env_hint(repo, "jacoco_agent", module, "pom")
                command = build_command(with_am=retried_with_am, goals=lifecycle)
                print("[tc-agent] the forked VM died with two JaCoCo agents - this pom binds "
                      "prepare-agent itself; re-running without ours, and remembering it.",
                      file=sys.stderr, flush=True)
                code, output, report_files, results = attempt()
            # The lean path needs a complete target/ and a surefire that is not
            # configured per execution. It can also "succeed" without running
            # anything, so SILENCE counts as a failure too: no reports, or only
            # skipped ones, falls back to the real phase instead of reporting
            # the tests as unavailable.
            #
            # Only when the goals RAN NOTHING. Tests that ran and failed, or test
            # sources that do not compile, are this run's result: the phase would
            # end the same way, minutes later, after every generator bound to it.
            ran = any(r["status"] != "SKIPPED" for r in results)
            test_compile_failed = bool(COMPILER_ERROR.search(output)) or "COMPILATION ERROR" in output
            if goals_only and not ran and not test_compile_failed:
                print("[tc-agent] the direct goals %s - falling back to the full `test` phase for "
                      "this run%s" % (
                          "ran no tests (maven exited %s)" % code,
                          "" if code != 0 else "; surefire is probably configured in a pom "
                          "execution, so `maven_goals_only` buys nothing here"),
                      file=sys.stderr, flush=True)
                goals_only = False
                command = build_command(with_am=retried_with_am, goals=["test"])
                code, output, report_files, results = attempt()
            runs.append(results)

        # A green suite is not run again - it would cost a full build to learn
        # almost nothing. A suite that FAILED is: that second run is the one
        # that separates a real failure from a flake.
        if planned == 1 and any(r["status"] in ("FAILED", "ERROR") for r in runs[0]):
            print("[tc-agent] a test failed - running the suite once more to tell a real failure "
                  "from a flake", file=sys.stderr, flush=True)
            code, output, report_files, confirmation = attempt()
            runs.append(confirmation)
        log = log_path   # written live by c.run

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

        agent_source = (f"pom-bound ({bound_pom})" if drop_agent
                        else f"cli goal ({jacoco})"
                        + (f" - the pom binds one too ({bound_pom}), but a pom execution does not "
                           "fire outside the lifecycle" if bound_pom else ""))

        executed = sum(1 for r in results if r["status"] != "SKIPPED")
        if not executed:
            raise c.CheckError(
                f"surefire ran 0 tests for -Dtest={','.join(selectors)} - check the "
                f"discovered class names and the module ({module or 'root'}); "
                f"full log: {log}"
            )
        if (not exec_file.exists() or exec_file.stat().st_size == 0) and drop_agent:
            # The hint was wrong, or stopped being true: the pom's execution did
            # not attach anything. Take the agent back and forget the hint.
            print("[tc-agent] the pom's agent produced nothing - re-running with ours and "
                  "forgetting that hint.", file=sys.stderr, flush=True)
            drop_agent = False
            c.save_env_hint(repo, "jacoco_agent", module, "cli")
            command = build_command(with_am=retried_with_am, goals=lifecycle)
            code, output, report_files, results = attempt()
            runs[-1] = results
            agent_source = f"cli goal ({jacoco})"

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

        # Written by the report goal of the same call, for tc_coverage.py to read.
        produced = c.recent_files(search_root, "**/jacoco.xml", run_started,
                                  prefer=("target/site/jacoco/jacoco.xml",))
        jacoco_xml = produced[-1] if produced else None

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
            "jacoco_xml": str(jacoco_xml) if jacoco_xml else None,
            "plugins_run": c.maven_goals_run(output),
            "maven_seconds": round(maven_seconds, 1),
            "lifecycle": " ".join(lifecycle) if goals_only else "test",
            "compiled_src_main": not skip_main,
            "module": module,
            "label": args.label,
            "exec_file": str(exec_file),
            "report_files": [str(f) for f in report_files],
        }
        summary = [
            f"{data['total']} tests, {data['failed']} failed, {data['skipped']} skipped",
            f"flaky across {len(runs)} runs: {', '.join(flaky) if flaky else 'none'}",
            f"jacoco agent: {agent_source}",
            f"maven took {round(maven_seconds)}s"
            + (" including compiling src/main" if not skip_main else "")
            + (" - goals: " + ", ".join(c.maven_goals_run(output)[:12])
               if c.maven_goals_run(output) else ""),
        ]
        if failures:
            phases = {f.get("failure_phase") for f in failures}
            summary.append("failure phases: " + ", ".join(sorted(p for p in phases if p)))
        code = 1 if (failures or flaky) else 0
        if code == 0:
            c.trim_log(log)   # a green check keeps only the tail of its maven log
        return c.finish(directory, name, "Check: tests", summary, data, code)

    except c.CheckError as exc:
        data = {"status": "UNAVAILABLE", "reason": str(exc)}
        if directory is not None:
            c.finish(directory, name, "Check: tests", [str(exc)[:300]], data, 2)
        return c.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())