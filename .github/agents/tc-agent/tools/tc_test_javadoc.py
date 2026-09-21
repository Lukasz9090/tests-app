#!/usr/bin/env python3
"""Tests for the in-code metadata (tc_javadoc.py) and the git facts (tc_git.py) — DEV TOOL.

In Model B the Javadoc tags ARE the pipeline's database, so a parser that
attaches a Javadoc to the wrong method, loses a tag, or rewrites more than the
`@characterizes` line corrupts state silently. Covered:

  * attaching Javadoc to test methods (annotations with strings and parens,
    braces inside string literals, javadoc after annotations, nested classes),
  * every metadata defect the parser reports,
  * placeholders (@Disabled + @deferred + empty body),
  * reseal: one line changes, CRLF preserved, nothing else touched,
  * sha prefix matching, dirty / age / branch helpers on a real git repo,
  * protected branches parsed from AGENTS.md.

Usage:
    python .github/agents/tc-agent/tools/tc_test_javadoc.py [--verbose]
Exit codes: 0 all passed, 1 a case failed, 2 the harness could not run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from tc_testkit import (FixtureRepo, ai_test, expect, expect_true, human_test,  # noqa: E402
                            run_all, make_test_class)
    import tc_common as c  # noqa: E402
    import tc_git as g  # noqa: E402
    import tc_javadoc as j  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)


TRICKY = r'''package com.acme;

/** Human class doc. */
@ExtendWith(MockitoExtension.class)
class OrderServiceTest {

    @Mock OrderRepository repo;

    @BeforeEach
    void setUp() { }

    /**
     * AI-generated test. Characterizes current behaviour of OrderService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @characterizes OrderService@29aeef6a
     * @note business-hours guard rejects 17:00 exactly — reported
     *       as a defect
     * @note second note
     */
    @Test
    @DisplayName("a (tricky) name with } brace")
    void shouldCreateOrderWhenCustomerActive() {
        String s = "}{ @Test void fake() {";
        char q = '"';
        // given
    }

    @Test
    void humanTest() { assertThat(1).isOne(); }

    @ParameterizedTest
    @ValueSource(ints = {1, 2})
    /**
     * AI-generated test.
     * @aiGenerated
     * @mode spec-driven
     */
    public void paramTest(int x) { }

    @Nested
    class Inner {
        @Test void innerHuman() { x(); }
    }
}
'''


def parse(text: str):
    return j.parse_text(text, "T.java")


def test_attaches_javadoc_to_the_right_methods():
    methods, defects = parse(TRICKY)
    keys = [m.key for m in methods]
    expect("finds exactly the four test methods (not setUp, not the string)",
           keys, ["OrderServiceTest#shouldCreateOrderWhenCustomerActive", "OrderServiceTest#humanTest",
                  "OrderServiceTest#paramTest", "OrderServiceTest$Inner#innerHuman"])
    first = methods[0]
    expect("legacy mode", first.meta.mode, "legacy")
    expect("characterizes class", first.meta.characterizes_class, "OrderService")
    expect("characterizes sha", first.meta.characterizes_sha, "29aeef6a")
    expect("continuation line joins the note",
           first.meta.notes[0], "business-hours guard rejects 17:00 exactly — reported as a defect")
    expect("repeatable @note", len(first.meta.notes), 2)
    expect("prose line", first.prose.startswith("AI-generated test."), True)
    expect("the class Javadoc does not leak into a human test", methods[1].meta.ai, False)
    expect("javadoc placed after annotations still attaches", methods[2].meta.mode, "spec-driven")
    expect("no file-level defects", defects, [])
    expect("line number points at the method name", first.line, 24)


def test_placeholder():
    text = make_test_class("OrderServiceTest", ai_test("shouldRejectWhenOutsideHours", "29aeef6a",
                                                  deferred="needs a Clock seam"))
    (m,), _ = parse(text)
    expect("placeholder recognised", m.is_placeholder, True)
    expect("disabled", m.disabled, True)
    expect("disabled reason", m.disabled_reason, "AI deferred: needs a Clock seam")
    expect("empty body", m.body_empty, True)
    expect("no defects", m.meta.defects, [])


def test_defects():
    cases = {
        "legacy without sha": ("/**\n * @aiGenerated\n * @mode legacy\n */\n@Test void a() {}",
                               "@mode legacy without @characterizes"),
        "no mode": ("/**\n * @aiGenerated\n */\n@Test void a() {}", "@aiGenerated without @mode"),
        "bad mode": ("/**\n * @aiGenerated\n * @mode tdd\n */\n@Test void a() {}",
                     "@mode 'tdd' is not one of legacy, spec-driven"),
        "bad sha": ("/**\n * @aiGenerated\n * @mode legacy\n * @characterizes OrderService\n */\n@Test void a() {}",
                    "@characterizes 'OrderService' is not <Class>@<sha>"),
        "tags without aiGenerated": ("/**\n * @mode legacy\n */\n@Test void a() {}",
                                     "AI tags without @aiGenerated"),
        "spec-driven with sha": ("/**\n * @aiGenerated\n * @mode spec-driven\n * @characterizes X@1234567\n */\n@Test void a() {}",
                                 "@mode spec-driven must not carry @characterizes"),
        "two tags on one line": ("/**\n * @aiGenerated @mode legacy\n */\n@Test void a() {}",
                                 "@aiGenerated is followed by '@mode legacy' - write one tag per line"),
        "deferred without Disabled": ("/**\n * @aiGenerated\n * @mode spec-driven\n * @deferred why\n */\n@Test void a() {}",
                                      "@deferred placeholder without @Disabled"),
        "deferred with body": ('/**\n * @aiGenerated\n * @mode spec-driven\n * @deferred why\n */\n'
                               '@Test @Disabled("AI deferred: why") void a() { x(); }',
                               "@deferred placeholder must have an empty body"),
        "Disabled marker without deferred": ('/**\n * @aiGenerated\n * @mode spec-driven\n */\n'
                                             '@Test @Disabled("AI deferred: why") void a() { }',
                                             '@Disabled("AI deferred: ...") without @deferred in the Javadoc'),
    }
    for label, (body, wanted) in cases.items():
        (m,), _ = parse("class T {\n" + body + "\n}\n")
        expect(f"defect: {label}", wanted in m.meta.defects, True)


def test_class_level_tags_are_a_defect():
    text = "/**\n * @aiGenerated\n * @mode legacy\n */\nclass T {\n" + human_test("a") + "}\n"
    methods, defects = parse(text)
    expect("the method stays human", methods[0].meta.ai, False)
    expect("one file-level defect", len(defects), 1)
    expect_true("it names the rule", "never on the class" in defects[0])


def test_human_javadoc_is_not_ai():
    text = "class T {\n/**\n * Checks something.\n * @see Foo\n */\n@Test void a() {}\n}\n"
    (m,), _ = parse(text)
    expect("human javadoc", (m.meta.ai, m.meta.has_ai_tags, m.meta.defects), (False, False, []))


def test_reseal_changes_one_line_and_keeps_crlf():
    with FixtureRepo() as repo:
        text = make_test_class("OrderServiceTest", ai_test("a", "29aeef6a"), ai_test("b", "29aeef6a"))
        path = repo.root / "T.java"
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        changed, detail = j.reseal(path, "OrderServiceTest#a", "OrderService", "4b1c2aa9")
        expect("reseal reports a change", changed, True)
        after = path.read_bytes().decode("utf-8")
        expect("CRLF preserved", after.count("\r\n"), text.count("\n"))
        expect("method a moved", "OrderService@4b1c2aa9" in after.split("void a()")[0], True)
        expect("method b untouched", after.split("void a()")[1].count("OrderService@29aeef6a"), 1)
        expect("only that sha changed", after.replace("4b1c2aa9", "29aeef6a"),
               text.replace("\n", "\r\n"))
        again, _ = j.reseal(path, "OrderServiceTest#a", "OrderService", "4b1c2aa9")
        expect("resealing to the same sha is a no-op", again, False)
        missing, _ = j.reseal(path, "OrderServiceTest#nope", "OrderService", "4b1c2aa9")
        expect("unknown method is reported, not guessed", missing, False)


def test_sha_matches():
    expect("same", g.sha_matches("29aeef6a", "29aeef6a"), True)
    expect("shorter recorded", g.sha_matches("29aeef6", "29aeef6a1"), True)
    expect("longer recorded", g.sha_matches("29aeef6a1", "29aeef6"), True)
    expect("case-insensitive", g.sha_matches("29AEEF6A", "29aeef6a"), True)
    expect("different", g.sha_matches("29aeef6a", "4b1c2aa9"), False)
    expect("too short to trust", g.sha_matches("29aee", "29aeef6a"), False)
    expect("missing", g.sha_matches(None, "29aeef6a"), False)


def test_git_facts():
    with FixtureRepo() as repo:
        target = repo.root / repo.target_path
        expect("short sha", g.short_sha(repo.root, target), repo.sha())
        expect("clean", g.is_dirty(repo.root, target), False)
        age = g.age_days(repo.root, target)
        expect_true("age about 30 days", 29.5 < age < 30.5)
        repo.change_target()
        expect("dirty after an edit", g.is_dirty(repo.root, target), True)
        expect("branch", g.current_branch(repo.root), "master")
        repo.git("checkout", "-q", "--detach")
        expect("detached HEAD has no branch", g.current_branch(repo.root), None)


def test_protected_branches():
    with FixtureRepo() as repo:
        expect("no AGENTS.md -> master only", c.protected_branches(repo.root), (["master"], "default"))
        repo.write("AGENTS.md", "# Notes\n\nNothing about branches.\n")
        expect("no line -> master only", c.protected_branches(repo.root)[0], ["master"])
        repo.write("AGENTS.md", "x\ntc-agent-protected-branches: master, main, release/*\n")
        expect("list with glob", c.protected_branches(repo.root), (["master", "main", "release/*"], "AGENTS.md"))
        repo.write("AGENTS.md", "- `tc-agent-protected-branches: develop`\n")
        expect("bullet and backticks tolerated", c.protected_branches(repo.root)[0], ["develop"])
        repo.write("AGENTS.md", "tc-agent-protected-branches:\n")
        expect("empty list -> master, never nothing", c.protected_branches(repo.root)[0], ["master"])


def test_discovery_and_target():
    with FixtureRepo() as repo:
        repo.write_test("OrderServiceTest", human_test("a"))
        repo.write("src/test/java/com/acme/OrderBuilder.java",
                   "package com.acme;\nclass OrderBuilder { OrderService s; }\n")
        repo.write_test("OtherTest", human_test("b"))
        repo.write_test("UsesOrderServiceIT", "    OrderService s;\n" + human_test("c"))
        target = c.resolve_target(repo.root, "OrderService.create")
        expect("fqcn", target.fqcn, "com.acme.OrderService")
        expect("method", target.method, "create")
        expect("root module", target.module, None)
        found = [fq for fq, _ in c.discover_test_classes(repo.root, target)]
        expect("tests by name and by mention, not builders or unrelated",
               found, ["com.acme.OrderServiceTest", "com.acme.UsesOrderServiceIT"])
        try:
            c.resolve_target(repo.root, "Nope")
            expect("unknown target raises", False, True)
        except c.TargetError as exc:
            expect("TARGET_NOT_FOUND", exc.code, "TARGET_NOT_FOUND")


if __name__ == "__main__":
    sys.exit(run_all(globals(), "METADATA_AND_GIT_OK"))
