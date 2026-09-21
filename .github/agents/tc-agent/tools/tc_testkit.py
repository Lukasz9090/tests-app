"""Shared harness for the tc-agent dev tests — DEV TOOL, not runtime.

Standard library only, no pytest, no maven. Each test file imports this, defines
`test_*` functions and calls `run_all(globals(), "<OK marker>")`.

`FixtureRepo` builds a throw-away Maven-shaped git repository (pom.xml, one
production class, test classes) so git-dependent logic — sha, dirty, age,
branches, commits — is exercised for real.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
TC = HERE.parents[1]
sys.path.insert(0, str(TC / "scripts"))

FAILURES: list = []
PASSED = 0
VERBOSE = False


def expect(label: str, actual, wanted) -> None:
    """One assertion. Never raises: a failing case must not hide the later ones."""
    global PASSED
    if actual == wanted:
        PASSED += 1
        if VERBOSE:
            print(f"  ok   {label}")
        return
    FAILURES.append(f"{label}\n         wanted: {wanted!r}\n         actual: {actual!r}")
    print(f"  FAIL {label}")


def expect_true(label: str, value) -> None:
    expect(label, bool(value), True)


def run_all(namespace: dict, ok_marker: str) -> int:
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    VERBOSE = parser.parse_args().verbose
    for name, body in sorted(namespace.items()):
        if name.startswith("test_") and callable(body):
            try:
                body()
            except Exception as exc:  # a crash is a failure, not an abort
                import traceback
                FAILURES.append(f"{name} crashed: {exc!r}\n{traceback.format_exc()}")
                print(f"  CRASH {name}: {exc!r}")
    print(f"\n{PASSED + len(FAILURES)} assertions: {PASSED} passed, {len(FAILURES)} failed")
    if FAILURES:
        print("\nFAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(ok_marker)
    return 0


POM = """<?xml version="1.0" encoding="UTF-8"?>
<project><modelVersion>4.0.0</modelVersion><groupId>x</groupId><artifactId>fixture</artifactId>
<version>1</version></project>
"""

TARGET = """package com.acme;

public class OrderService {
    public int create(int amount) {
        if (amount <= 0) {
            throw new IllegalArgumentException("amount");
        }
        return amount;
    }
}
"""


def ai_test(name: str, sha: str | None, mode: str = "legacy", deferred: str | None = None,
            notes: list | None = None, interactive: bool = False, cls: str = "OrderService") -> str:
    tags = ["@aiGenerated", f"@mode {mode}"]
    if interactive:
        tags.append("@interactive")
    if sha:
        tags.append(f"@characterizes {cls}@{sha}")
    if deferred:
        tags.append(f"@deferred {deferred}")
    for n in notes or []:
        tags.append(f"@note {n}")
    doc = "    /**\n     * AI-generated test.\n     *\n" + "".join(f"     * {t}\n" for t in tags) + "     */\n"
    if deferred:
        return doc + (f'    @Test\n    @Disabled("AI deferred: {deferred}")\n'
                      f"    void {name}() {{\n    }}\n")
    return doc + (f"    @Test\n    void {name}() {{\n        // given\n        // when\n"
                  f"        // then\n        assertThat(1).isOne();\n    }}\n")


def human_test(name: str) -> str:
    return f"    @Test\n    void {name}() {{\n        assertThat(1).isOne();\n    }}\n"


def make_test_class(name: str, *methods: str) -> str:
    return (f"package com.acme;\n\nimport org.junit.jupiter.api.*;\n\nclass {name} {{\n\n"
            + "\n".join(methods) + "}\n")


class FixtureRepo:
    """A temporary git repository shaped like a single-module Maven project."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="tc-fixture-"))
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.email", "fixture@example.com")
        self.git("config", "user.name", "Fixture")
        self.git("config", "commit.gpgsign", "false")
        self.write("pom.xml", POM)
        self.write("src/main/java/com/acme/OrderService.java", TARGET)
        self.commit("initial", days_ago=30)

    # ------------------------------------------------------------- files ---
    @property
    def target_path(self) -> str:
        return "src/main/java/com/acme/OrderService.java"

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def write_test(self, cls: str, *methods: str) -> str:
        rel = f"src/test/java/com/acme/{cls}.java"
        self.write(rel, make_test_class(cls, *methods))
        return rel

    # --------------------------------------------------------------- git ---
    def git(self, *args: str, env: dict | None = None) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                              env={**os.environ, **(env or {})})
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
        return proc.stdout.strip()

    def commit(self, message: str, days_ago: float = 0) -> str:
        import time
        stamp = int(time.time() - days_ago * 86400)
        date = f"@{stamp} +0000"
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message,
                 env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
        return self.sha()

    def sha(self, path: str | None = None) -> str:
        path = path or self.target_path
        return self.git("log", "-1", "--format=%h", "--", path)

    def change_target(self, body: str = "return amount + 0;") -> None:
        text = self.read(self.target_path).replace("return amount;", body)
        self.write(self.target_path, text)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()


class FakeRunner:
    """Stands in for the maven-driven checks: returns canned (exit, payload)."""

    def __init__(self, tests=None, coverage=None, mutation=None):
        self._tests = tests if tests is not None else (0, {"status": "PASSED", "failures": []})
        self._coverage = coverage if coverage is not None else (
            0, {"status": "PASSED", "branch_ratio": 0.9, "gate": 0.8, "uncovered": []})
        self._mutation = mutation if mutation is not None else (
            0, {"status": "PASSED", "score": 0.8, "gate": 0.7, "survivors": []})
        self.calls = []

    def tests(self):
        self.calls.append("tests")
        return self._tests

    def coverage(self):
        self.calls.append("coverage")
        return self._coverage

    def mutation(self):
        self.calls.append("mutation")
        return self._mutation


def failing(*tests: str, phase: str = "assertion") -> tuple:
    return (1, {"status": "FAILED", "failures": [
        {"test": t, "status": "FAILED", "failure_phase": phase, "message": "boom",
         "location": "X.java:1"} for t in tests]})
