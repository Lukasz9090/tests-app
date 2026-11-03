#!/usr/bin/env python3
"""Plumbing tests for the maven-driven check scripts — DEV TOOL, not runtime.

tc_run_tests.py, tc_coverage.py and tc_mutation.py no longer read a plan: they
resolve the target from its name, discover the test classes that exercise it
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
                           "--mode", "characterization", *extra], capture_output=True, text=True, env=full_env)
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
        expect("two maven calls: tests+report, then pit", len(out["mvn"]), 2)
        expect_true("-Dtest is the discovered class only", "-Dtest=OrderServiceTest " in out["mvn"][0] + " ")
        expect_true("exec file is per label", "jacoco-entry.exec" in out["mvn"][0])
        expect_true("the report goal rides along", "jacoco-maven-plugin" in out["mvn"][0]
                    and ":report" in out["mvn"][0])
        expect_true("and reads the same exec", "-Djacoco.dataFile=" in out["mvn"][0])
        expect_true("PIT targets the target class", "-Dpit.targetClasses=com.acme.OrderService" in out["mvn"][1])
        coverage = load_payload(out["dir"] / "checks" / "coverage-entry.md")[0]
        expect("coverage started no maven of its own", coverage["maven_seconds"], 0.0)
        # ... but it must still work when that report never happened.
        Path(coverage["report"]).unlink()
        before = len(out["mvn"])
        again = subprocess.run(
            [sys.executable, str(TC / "scripts" / "tc_coverage.py"), "OrderService",
             "--repo", str(repo.root), "--run", out["run_dir"].rsplit("/", 1)[-1],
             "--label", "entry"],
            capture_output=True, text=True,
            env={**os.environ, "PATH": f"{FAKE}{os.pathsep}{os.environ['PATH']}",
                 "FAKE_MVN_LOG": str(repo.root / "mvn.log")})
        expect("the fallback report is green too", again.returncode, 0)
        expect("and it did start maven",
               len((repo.root / "mvn.log").read_text().splitlines()), before + 1)
        checks = sorted(p.name for p in (out["dir"] / "checks").glob("*.md"))
        expect("reports in the run directory", checks,
               ["coverage-entry.md", "mutation-entry.md", "tests-entry.md"])
        tests = load_payload(out["dir"] / "checks" / "tests-entry.md")[0]
        expect("placeholder counted as skipped", (tests["total"], tests["skipped"]), (3, 1))


def test_a_green_suite_is_not_run_twice_but_a_failing_one_is():
    """The second build is worth paying for only after a failure."""
    with fixture() as repo:
        out = start(repo)
        tests = load_payload(out["dir"] / "checks" / "tests-entry.md")[0]
        expect("green: one run", tests["runs"], 1)
        expect("so one maven call for the tests", len(out["mvn"]), 2)   # tests+report, pit
    with fixture() as repo:
        out = start(repo, {"FAKE_MVN_FAIL": "OrderServiceTest#humanB"})
        tests = load_payload(out["dir"] / "checks" / "tests-entry.md")[0]
        expect("red: the suite is confirmed once", tests["runs"], 2)
        expect("a failure in both runs is not a flake", tests["flaky"], [])


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
        expect("PIT not run - one call did tests and the report", len(out["mvn"]), 1)


def test_mutation_gap_plans():
    with fixture() as repo:
        out = start(repo, {"FAKE_MVN_MUTANTS": "1,3"})
        expect("PLAN / MUTATION_GAP", (out["state"]["next_action"], out["state"]["reasons"]),
               ("PLAN", ["MUTATION_GAP"]))
        expect("survivors", len(out["state"]["mutation"]["survivors"]), 3)


def test_stale_and_failing_goes_to_planner_then_reseal_path():
    with fixture() as repo:
        repo.change_target("return amount * 2;")
        repo.commit("behavior change", days_ago=10)
        out = start(repo, {"FAKE_MVN_FAIL": "OrderServiceTest#shouldA"})
        state = out["state"]
        expect("PLAN / STALE (placeholder too)", (state["next_action"], state["reasons"]), ("PLAN", ["STALE"]))
        expect("recharacterize", sorted(r["method"] for r in state["recharacterize"]),
               ["OrderServiceTest#shouldA", "OrderServiceTest#shouldC"])
        out2 = start(repo)
        expect("green again -> reseal list", [r["method"] for r in out2["state"]["reseal"]],
               ["OrderServiceTest#shouldA"])


def test_untested_method_plans_even_when_gate_passes():
    with fixture() as repo:
        out = start(repo, {"FAKE_MVN_UNTESTED": "create"})
        state = out["state"]
        expect("PLAN / UNTESTED_METHODS despite a passing gate",
               (state["next_action"], state["reasons"], state["coverage"]["status"]),
               ("PLAN", ["UNTESTED_METHODS"], "PASSED"))
        expect("names the method", [m["name"] for m in state["coverage"]["untested_methods"]], ["create"])


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


def test_maven_timeout_is_a_clear_error():
    """A build that never returns must not look like a hung script."""
    import tc_common as tc
    with FixtureRepo() as repo:
        try:
            tc.run([sys.executable, "-c", "import time; time.sleep(5)"], repo.root, timeout=0.5)
        except tc.CheckError as exc:
            expect_true("names the limit", "did not finish within" in str(exc))
            expect_true("suggests what to do", "maven_timeout_seconds" in str(exc))
        else:
            expect("timeout raised CheckError", True, False)


def test_output_survives_a_lingering_grandchild():
    """Maven leaves children behind; the read must end with the PROCESS, not the pipe."""
    import tc_common as tc
    with FixtureRepo() as repo:
        script = ("import subprocess, sys, time;"
                  "print('BUILD SUCCESS', flush=True);"
                  "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
                  "sys.exit(0)")
        code, output = tc.run([sys.executable, "-c", script], repo.root, timeout=10)
        expect("the parent's exit code is returned", code, 0)
        expect_true("its output is complete", "BUILD SUCCESS" in output)


def test_also_make_is_auto_by_default():
    import tc_common as tc
    with FixtureRepo() as repo:
        expect("auto by default", tc.maven_also_make(repo.root), "auto")
        expect("auto means: try without -am first",
               tc.module_args("mod", also_make=(tc.maven_also_make(repo.root) is True)),
               ["-pl", "mod"])
        for value, wanted in ((True, True), (False, False)):
            repo.write(".github/agents/tc-agent-project/profile.md",
                       '# p\n\n```json\n{"schema_version": 1, "maven_also_make": %s}\n```\n'
                       % str(value).lower())
            tc._PROFILE_CACHE.clear()
            expect(f"profile {value}", tc.maven_also_make(repo.root), wanted)
        tc._PROFILE_CACHE.clear()


def test_class_lookup_uses_git_and_sees_uncommitted_files():
    import tc_common as tc
    with FixtureRepo() as repo:
        tc._GIT_INDEX_CACHE.clear()
        expect_true("git answers", tc.git_index(repo.root) is not None)
        # a test the generator just wrote: untracked, and it must still be found
        rel = repo.write_test("OrderServiceTest", human_test("shouldA"))
        tc._GIT_INDEX_CACHE.clear()
        found = [f.name for f in tc.java_files(tc.find_roots(repo.root)[1])]
        expect_true("untracked test is visible", "OrderServiceTest.java" in found)
        # and something git ignores stays out of the index
        repo.write("target/generated-sources/api/com/acme/Gen.java", "class Gen {}\n")
        repo.write(".gitignore", "target/\n")
        tc._GIT_INDEX_CACHE.clear()
        src = [f.name for f in tc.java_files(tc.find_roots(repo.root)[0])]
        expect_true("build output is not in the index", "Gen.java" not in src)
        walked = [f.name for f in tc.java_files([repo.root / "target/generated-sources"],
                                                use_git=False)]
        expect_true("but a walk still finds it", "Gen.java" in walked)
        tc._GIT_INDEX_CACHE.clear()


def test_progress_reaches_the_terminal():
    """A long maven call must print a heartbeat, not silence."""
    import io, contextlib, os, stat
    import tc_common as tc
    with FixtureRepo() as repo:
        fake = repo.root / "mvn"
        fake.write_text("#!/bin/sh\nsleep 2\necho BUILD SUCCESS\n", encoding="utf-8")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        old, tc.HEARTBEAT_SECONDS = tc.HEARTBEAT_SECONDS, 1
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stderr(buffer):
                code, output = tc.run([str(fake)], repo.root, timeout=30)
        finally:
            tc.HEARTBEAT_SECONDS = old
        noise = buffer.getvalue()
        expect("the call still returns its output", (code, "BUILD SUCCESS" in output), (0, True))
        expect_true("the command is echoed", "$ " in noise)
        expect_true("and it says it is alive", "still running" in noise)


def test_the_maven_log_survives_a_timeout():
    """The log is the only evidence of a build that was stopped - it must exist."""
    import os, stat
    import tc_common as tc
    with FixtureRepo() as repo:
        fake = repo.root / "mvn"
        fake.write_text("#!/bin/sh\necho STARTING BUILD\nsleep 30\n", encoding="utf-8")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        log = repo.root / "checks" / "maven-tests-entry.log"
        old, tc.HEARTBEAT_SECONDS = tc.HEARTBEAT_SECONDS, 5
        try:
            tc.run([str(fake)], repo.root, timeout=1, log_path=log)
        except tc.CheckError as exc:
            expect_true("the error names the limit", "did not finish within" in str(exc))
        else:
            expect("a timeout was raised", True, False)
        finally:
            tc.HEARTBEAT_SECONDS = old
        expect_true("the log is on disk", log.is_file())
        text = log.read_text(encoding="utf-8")
        expect_true("with the command", text.startswith("$ "))
        expect_true("and what maven printed before it was stopped", "STARTING BUILD" in text)


def test_missing_dependencies_are_recognised():
    import tc_common as tc
    expect("maven's wording is matched", tc.needs_also_make(
        "[ERROR] Failed to execute goal on project ces-pl-rest: Could not resolve dependencies "
        "for project com.acme:ces-pl-rest:jar:2.101.0-SNAPSHOT"), True)
    expect("a normal failure is not", tc.needs_also_make(
        "[ERROR] Tests run: 3, Failures: 1"), False)


def test_skipping_main_compile_needs_built_classes():
    import tc_common as tc
    with FixtureRepo() as repo:
        expect("auto by default", tc.maven_skip_main_compile(repo.root), "auto")
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "maven_skip_main_compile": true}\n```\n')
        tc._PROFILE_CACHE.clear()
        expect("forced from the profile", tc.maven_skip_main_compile(repo.root), True)
        expect("nothing built yet -> no skipping", tc.built_classes(repo.root, None), None)
        classes = repo.root / "target" / "classes" / "com" / "acme"
        classes.mkdir(parents=True)
        (classes / "OrderService.class").write_bytes(b"\xca\xfe\xba\xbe")
        found = tc.built_classes(repo.root, None)
        expect_true("built classes are found", found is not None)
        expect("nothing is newer than them", tc.stale_classes(repo.root, None, found), None)
        import time as _t
        old_source = repo.root / "src/main/java/com/acme/Helpers.java"
        old_source.write_text("class Util {}\n", encoding="utf-8")
        import os as _os
        then = (classes / "OrderService.class").stat().st_mtime - 3600
        _os.utime(old_source, (then, then))
        expect("a source the build chose not to compile is NOT stale",
               tc.stale_classes(repo.root, None, found), None)
        old_source.unlink()
        new_source = repo.root / "src/main/java/com/acme/Added.java"
        _t.sleep(0.05)
        new_source.write_text("class Added {}\n", encoding="utf-8")
        expect("a source younger than the whole build is stale",
               tc.stale_classes(repo.root, None, found),
               ("src/main/java/com/acme/Added.java", "missing"))
        new_source.unlink()
        _t.sleep(0.05)
        (repo.root / repo.target_path).write_text("class OrderService { int x; }\n", encoding="utf-8")
        stale = tc.stale_classes(repo.root, None, found)
        expect_true("a newer source is reported", (stale or ("", ""))[0].endswith("OrderService.java"))
        expect("and says why", (stale or ("", ""))[1], "newer")


def test_auto_asks_about_the_class_under_test():
    """A module member nobody in this run touches must not force a rebuild.

    In a repo that is pulled daily something under src/main is always newer
    than its class, so the module-wide question answered "rebuild" forever -
    6500 files, minutes, for a file the measurement never reads.
    """
    import tc_common as tc
    with FixtureRepo() as repo:
        expect("auto by default", tc.maven_skip_main_compile(repo.root), "auto")
        classes = repo.root / "target" / "classes" / "com" / "acme"
        classes.mkdir(parents=True)
        for name in ("OrderService", "Other"):
            (classes / f"{name}.class").write_bytes(b"\xca\xfe\xba\xbe")
        built = tc.built_classes(repo.root, None)
        target = repo.root / repo.target_path
        other = repo.root / "src/main/java/com/acme/Other.java"
        other.write_text("class Other {}\n", encoding="utf-8")
        import time as _t
        _t.sleep(0.05)
        other.touch()
        expect_true("the module-wide question sees the other file",
                    (tc.stale_classes(repo.root, None, built) or ("",))[0].endswith("Other.java"))
        expect("the target's own question does not",
               tc.stale_target(repo.root, None, built, target), None)
        _t.sleep(0.05)
        target.touch()
        expect("and does see the target when it moves",
               tc.stale_target(repo.root, None, built, target),
               (repo.target_path, "newer"))
        expect("a source outside the module is not compared",
               tc.stale_target(repo.root, None, built, repo.root / "pom.xml"), None)
        expect("strict is still available",
               tc.maven_skip_main_compile(repo.root), "auto")
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, '
                   '"maven_skip_main_compile": "strict"}\n```\n')
        tc._PROFILE_CACHE.clear()
        expect("and selectable", tc.maven_skip_main_compile(repo.root), "strict")
        tc._PROFILE_CACHE.clear()
        tc._PROFILE_CACHE.clear()


def test_goals_only_needs_a_built_src_main():
    import tc_common as tc
    with FixtureRepo() as repo:
        expect("on by default", tc.maven_goals_only(repo.root), True)
        expect("the lean goals replace the phase", tc.maven_lifecycle(repo.root, skip_main=True),
               ["resources:testResources", "compiler:testCompile", "surefire:test"])
        expect_true("test resources are copied, or a test reading one would fail",
                    "resources:testResources" in tc.LEAN_GOALS)
        expect("but never when src/main still has to be compiled",
               tc.maven_lifecycle(repo.root, skip_main=False), ["test"])
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "maven_goals_only": false}\n```\n')
        tc._PROFILE_CACHE.clear()
        expect("a repo that needs the phase can say so", tc.maven_goals_only(repo.root), False)
        expect("and gets it", tc.maven_lifecycle(repo.root, skip_main=True), ["test"])
        tc._PROFILE_CACHE.clear()


def test_junit_version_follows_the_existing_tests():
    """The poms lie more often than the tests do.

    `spring-boot-starter-test` was taken as proof of JUnit 5 - but before Boot
    2.2 that starter IS JUnit 4, and a repo can declare the platform while every
    test still runs on JUnit 4. Surefire does not fail a @Test of the wrong
    version, it silently does not run it, so what the neighbours import decides.
    """
    import tc_common as tc
    pom = ('<?xml version="1.0"?><project><modelVersion>4.0.0</modelVersion>'
           "<groupId>x</groupId><artifactId>fixture</artifactId><version>1</version>%s</project>")
    boot = ("<parent><groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-parent</artifactId><version>%s</version></parent>"
            "<dependencies><dependency><groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-test</artifactId></dependency></dependencies>")
    with FixtureRepo() as repo:
        repo.write("pom.xml", pom % "<dependencies><dependency><groupId>junit</groupId>"
                                    "<artifactId>junit</artifactId></dependency></dependencies>")
        tc._PROFILE_CACHE.clear()
        expect("a plain junit dependency is JUnit 4",
               tc.repo_contract(repo.root, None)["junit"], "4")

        repo.write("pom.xml", pom % (boot % "2.1.9.RELEASE"))
        expect("the starter before Boot 2.2 is not JUnit 5",
               tc.repo_contract(repo.root, None)["junit"], None)
        repo.write("pom.xml", pom % (boot % "2.6.3"))
        contract = tc.repo_contract(repo.root, None)
        expect("from Boot 2.2 on it is", (contract["junit"], contract["junit_source"]),
               ("5", "pom"))

        repo.write("src/test/java/com/acme/LegacyTest.java",
                   "package com.acme;\nimport org.junit.Test;\nimport org.junit.Assert;\n"
                   "public class LegacyTest { @Test public void a() {} }\n")
        contract = tc.repo_contract(repo.root, None)
        expect("but a JUnit 4 test in the module wins over the pom", contract["junit"], "4")
        expect_true("and says where that came from",
                    contract["junit_source"].startswith("existing tests"))
        expect("one flavor only is not mixed", contract["junit_mixed"], False)

        repo.write("src/test/java/com/acme/ModernTest.java",
                   "package com.acme;\nimport org.junit.jupiter.api.Test;\n"
                   "class ModernTest { @Test void b() {} }\n")
        repo.write("src/test/java/com/acme/AlsoModernTest.java",
                   "package com.acme;\nimport org.junit.jupiter.api.Test;\n"
                   "class AlsoModernTest { @Test void b() {} }\n")
        contract = tc.repo_contract(repo.root, None)
        expect("the majority decides", contract["junit"], "5")
        expect("and both present is flagged", contract["junit_mixed"], True)

        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "junit": "4"}\n```\n')
        tc._PROFILE_CACHE.clear()
        contract = tc.repo_contract(repo.root, None)
        expect("the profile overrides everything", (contract["junit"], contract["junit_source"]),
               ("4", "profile"))
        tc._PROFILE_CACHE.clear()


def test_a_pom_bound_agent_still_has_to_be_asked_for_on_the_lean_path():
    """prepare-agent is bound to a PHASE, so calling goals directly skips it.

    Symptom when it is missed: "7 tests ran but jacoco-v1-r1.exec is
    missing/empty" - the tests run, the agent never attaches, coverage and
    mutation have nothing to read.
    """
    with fixture() as repo:
        repo.write("pom.xml",
                   '<?xml version="1.0"?><project><modelVersion>4.0.0</modelVersion>'
                   "<groupId>x</groupId><artifactId>fixture</artifactId><version>1</version>"
                   "<build><plugins><plugin><artifactId>jacoco-maven-plugin</artifactId>"
                   "<executions><execution><goals><goal>prepare-agent</goal></goals>"
                   "</execution></executions></plugin></plugins></build></project>")
        compiled = repo.root / "target" / "classes" / "com" / "acme"
        compiled.mkdir(parents=True)
        (compiled / "OrderService.class").write_bytes(b"\xca\xfe\xba\xbe")
        out = start(repo)
        expect_true("the lean path ran", "surefire:test" in out["mvn"][0])
        expect_true("and asked for the agent itself", ":prepare-agent" in out["mvn"][0])
        tests = load_payload(out["dir"] / "checks" / "tests-entry.md")[0]
        expect_true("the payload says where the agent came from",
                    tests["jacoco_agent"].startswith("cli goal"))

        # ... and when the pom's own execution DOES fire on top of ours, the
        # forked VM dies - which the run recognises and heals by itself.
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "maven_goals_only": false}\n```\n')
        (repo.root / "mvn.log").unlink()           # only the next run's calls
        out = start(repo, {"FAKE_MVN_POM_AGENT": "1"})
        expect("the run is still DONE", out["state"]["next_action"], "DONE")
        expect_true("the first try asked for the agent", ":prepare-agent" in out["mvn"][0])
        expect_true("the retry did not", ":prepare-agent" not in out["mvn"][1])
        tests = load_payload(out["dir"] / "checks" / "tests-entry.md")[0]
        expect_true("and the payload credits the pom",
                    tests["jacoco_agent"].startswith("pom-bound"))
        expect("the answer is remembered", c.env_hint(repo.root, "jacoco_agent", None), "pom")

        # Next round: no doomed attempt, because the hint is already there.
        (repo.root / "mvn.log").unlink()
        out = start(repo, {"FAKE_MVN_POM_AGENT": "1"})
        expect("two calls, not three - the first one is skipped", len(out["mvn"]), 2)
        expect_true("none of them asks for the agent", ":prepare-agent" not in out["mvn"][0])

        # ... and the hint is disproved the moment the pom stops attaching one.
        (repo.root / "mvn.log").unlink()
        out = start(repo, {"FAKE_MVN_POM_AGENT": "1", "FAKE_MVN_NO_EXEC": "1"})
        expect_true("the run takes the agent back", ":prepare-agent" in out["mvn"][-1])
        expect("and forgets the hint", c.env_hint(repo.root, "jacoco_agent", None), "cli")


def test_silent_goals_fall_back_to_the_real_phase():
    """A surefire configured per execution runs nothing from the CLI and exits 0.

    That used to surface as "no surefire reports written (maven exited 0)" -
    tests UNAVAILABLE, review BLOCKED. Now the run notices it executed nothing
    and pays for the full phase once.
    """
    with fixture() as repo:
        compiled = repo.root / "target" / "classes" / "com" / "acme"
        compiled.mkdir(parents=True)
        (compiled / "OrderService.class").write_bytes(b"\xca\xfe\xba\xbe")
        out = start(repo, {"FAKE_MVN_GOALS_SILENT": "1"})
        expect("the run still finishes", out["state"]["next_action"], "DONE")
        calls = out["mvn"]
        expect("three maven calls: goals, the phase, pit", len(calls), 3)
        expect_true("the lean goals went first", "surefire:test" in calls[0])
        expect_true("src/main was skipped there", "-Dmaven.main.skip=true" in calls[0])
        expect_true("then the real phase", " test " in calls[1] + " "
                    and "surefire:test" not in calls[1])
        tests = load_payload(out["dir"] / "checks" / "tests-entry.md")[0]
        expect("and the tests were measured", tests["total"], 3)


def test_failing_or_broken_tests_never_fall_back_to_the_phase():
    """A red test or a test that does not compile is the result, not a goals problem.

    The phase would end the same way, minutes later, after every generator bound to it.
    """
    def lean_fixture(repo):
        compiled = repo.root / "target" / "classes" / "com" / "acme"
        compiled.mkdir(parents=True)
        (compiled / "OrderService.class").write_bytes(b"\xca\xfe\xba\xbe")

    with fixture() as repo:
        lean_fixture(repo)
        out = start(repo, {"FAKE_MVN_FAIL": "OrderServiceTest#humanB"})
        tests_calls = [cmd for cmd in out["mvn"] if "mutationCoverage" not in cmd]
        expect("failing test: goals + the confirmation run, both lean",
               (len(tests_calls), all("surefire:test" in cmd for cmd in tests_calls)), (2, True))
    with fixture() as repo:
        lean_fixture(repo)
        out = start(repo, {"FAKE_MVN_COMPILE": "cannot find symbol"})
        expect("compile error: one lean call, no phase", [("surefire:test" in cmd) for cmd in out["mvn"]], [True])
        expect("reported as a compile error", out["state"]["reasons"], ["COMPILE_ERROR"])


def test_maven_args_from_the_profile_reach_the_command():
    import tc_common as tc
    with FixtureRepo() as repo:
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "maven_args": ["-o", "-T", "1C"], '
                   '"maven_timeout_seconds": 60}\n```\n')
        tc._PROFILE_CACHE.clear()
        expect("args", tc.maven_args(repo.root), ["-o", "-T", "1C"])
        expect("timeout", tc.maven_timeout(repo.root), 60)
        expect("and they ride on the shared base", tc.mvn_base(repo.root)[1:],
               ["-B", "-nsu", "-o", "-T", "1C"])
        tc._PROFILE_CACHE.clear()


def test_a_run_does_not_re_resolve_snapshots():
    """Two checks of one run must see the same dependencies - and not wait for them."""
    import tc_common as tc
    with FixtureRepo() as repo:
        expect("off by default", tc.maven_snapshot_updates(repo.root), False)
        expect("so -nsu is on every call", tc.mvn_base(repo.root)[1:], ["-B", "-nsu"])
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "maven_snapshot_updates": true}\n```\n')
        tc._PROFILE_CACHE.clear()
        expect("the profile can give maven its usual behavior back",
               tc.mvn_base(repo.root)[1:], ["-B"])
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "maven_args": ["-nsu"]}\n```\n')
        tc._PROFILE_CACHE.clear()
        expect("and it is never passed twice", tc.mvn_base(repo.root)[1:], ["-B", "-nsu"])
        tc._PROFILE_CACHE.clear()


def test_missing_run_is_exit_2():
    with fixture() as repo:
        proc = subprocess.run([sys.executable, str(TC / "scripts" / "tc_coverage.py"), "OrderService",
                               "--repo", str(repo.root), "--run", "nope"], capture_output=True, text=True)
        expect("exit 2", proc.returncode, 2)
        expect_true("says why", "not found" in proc.stderr)


if __name__ == "__main__":
    sys.exit(run_all(globals(), "CHECK_SCRIPTS_OK"))
