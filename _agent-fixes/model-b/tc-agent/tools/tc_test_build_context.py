#!/usr/bin/env python3
"""Tests for the context pack's REPO CONVENTIONS section — DEV TOOL, not runtime.

The agent's own conventions travel with the agent (tc-test-conventions.md); the
repository can only tune style, and it does so through instruction files the
pack injects. Covered: which files are picked up and in what order, `applyTo`
filtering (match, no match, no front-matter, brace globs, `**`), extra paths
from the profile (also outside .github), the "none found" line, the precedence
header, and the per-test-class counts of AI-generated methods and placeholders.

Usage:
    python .github/agents/tc-agent/tools/tc_test_build_context.py [--verbose]
Exit codes: 0 all passed, 1 a case failed, 2 the harness could not run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from tc_testkit import TC, FixtureRepo, ai_test, expect, expect_true, human_test, run_all  # noqa: E402
    import tc_build_context as bc  # noqa: E402
    import tc_common as c  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)


def build(repo: FixtureRepo) -> str:
    directory = c.runs_root(repo.root, "OrderService") / "r1"
    directory.mkdir(parents=True, exist_ok=True)
    c.save_run(directory, {"run_id": "r1", "slug": "OrderService"})
    proc = subprocess.run([sys.executable, str(TC / "scripts" / "tc_build_context.py"), "OrderService",
                           "--repo", str(repo.root), "--run", "r1"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)
    return (directory / "context-pack.md").read_text(encoding="utf-8")


def section(pack: str) -> str:
    start = pack.index("## REPO CONVENTIONS")
    return pack[start:pack.index("## TARGET")]


def test_glob():
    rx = bc.glob_regex
    expect("** matches deep", bool(rx("src/test/**").match("src/test/java/com/acme/X.java")), True)
    expect("**/ matches zero dirs", bool(rx("**/*Test.java").match("XTest.java")), True)
    expect("* stays in one segment", bool(rx("src/*.java").match("src/a/b.java")), False)
    expect("braces", bool(rx("**/*.{java,kt}").match("a/b.kt")), True)


def test_none_found():
    with FixtureRepo() as repo:
        pack = build(repo)
        expect_true("says agent defaults apply", "none found — agent defaults (tc-test-conventions.md §B) apply" in pack)
        expect_true("precedence header always present", "pipeline integrity" in section(pack))


def test_pickup_and_applyto():
    with FixtureRepo() as repo:
        repo.write(".github/copilot-instructions.md", "Use British spelling.")
        repo.write(".github/instructions/testing.instructions.md",
                   '---\napplyTo: "src/test/**"\n---\nName tests method_expected_condition.')
        repo.write(".github/instructions/frontend.instructions.md",
                   '---\napplyTo: "web/**/*.ts"\n---\nFRONTEND ONLY')
        repo.write(".github/instructions/general.instructions.md", "No front-matter: always.")
        repo.write("AGENTS.md", "tc-agent-protected-branches: master\n")
        repo.write("docs/code-conventions.instruction.md", "Outside .github.")
        repo.write(".github/agents/tc-agent/tc-project-profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "instruction_paths": ["docs/code-conventions.instruction.md"]}\n```\n')
        c._PROFILE_CACHE.clear()
        pack = build(repo)
        sec = section(pack)
        expect_true("copilot-instructions", "Use British spelling." in sec)
        expect_true("applyTo matching the planned test file", "method_expected_condition" in sec)
        expect_true("no front-matter applies", "No front-matter: always." in sec)
        expect("applyTo not matching is left out", "FRONTEND ONLY" in pack, False)
        expect_true("AGENTS.md", "tc-agent-protected-branches" in sec)
        expect_true("profile instruction_paths outside .github", "Outside .github." in sec)
        order = [sec.index(x) for x in ("copilot-instructions.md (", "general.instructions.md (",
                                        "testing.instructions.md (", "AGENTS.md (", "code-conventions")]
        expect("documented order", order, sorted(order))


def test_existing_test_counts():
    with FixtureRepo() as repo:
        sha = repo.sha()
        repo.write_test("OrderServiceTest", ai_test("a", sha), ai_test("b", sha, deferred="why"), human_test("c"))
        pack = build(repo)
        expect_true("counts in the EXISTING TEST header",
                    "3 test methods: 1 AI-generated, 1 placeholders, 1 human" in pack)


if __name__ == "__main__":
    sys.exit(run_all(globals(), "BUILD_CONTEXT_OK"))
