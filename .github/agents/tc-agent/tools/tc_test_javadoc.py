#!/usr/bin/env python3
"""Tests for the in-code metadata (tc_javadoc.py) and the git facts (tc_git.py) — DEV TOOL.

The Javadoc tags ARE the pipeline's database, so a parser that
attaches a Javadoc to the wrong method, loses a tag, or rewrites more than the
`tc-agent-characterizes` line corrupts state silently. Covered:

  * attaching Javadoc to test methods (annotations with strings and parens,
    braces inside string literals, javadoc after annotations, nested classes),
  * every metadata defect the parser reports,
  * placeholders (@Disabled + tc-agent-deferred + empty body),
  * reseal: one line changes, CRLF preserved, nothing else touched,
  * sha prefix matching, dirty / age / branch helpers on a real git repo,
  * protected branches read from the project profile.

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
     * AI-generated test. Characterizes current behavior of OrderService (a freeze, not a spec).
     *
     * tc-agent-mode: characterization, interactive: true
     * tc-agent-characterizes: OrderService@29aeef6a
     * tc-agent-note: business-hours guard rejects 17:00 exactly — reported
     *       as a defect
     * tc-agent-note: second note
     * @see OrderService
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
     * tc-agent-mode: spec-driven, interactive: false
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
    expect("characterization mode", first.meta.mode, "characterization")
    expect("characterizes class", first.meta.characterizes_class, "OrderService")
    expect("characterizes sha", first.meta.characterizes_sha, "29aeef6a")
    expect("continuation line joins the note",
           first.meta.notes[0], "business-hours guard rejects 17:00 exactly — reported as a defect")
    expect("repeatable tc-agent-note", len(first.meta.notes), 2)
    expect("prose line", first.prose.startswith("AI-generated test."), True)
    expect("the class Javadoc does not leak into a human test", methods[1].meta.ai, False)
    expect("javadoc placed after annotations still attaches", methods[2].meta.mode, "spec-driven")
    expect("no file-level defects", defects, [])
    expect("line number points at the method name", first.line, 24)


def test_placeholder():
    text = make_test_class("OrderServiceTest", ai_test("shouldRejectWhenOutsideHours", "29aeef6a",
                                                  deferred="needs a Clock seam"))
    (m,), _ = parse(text)
    expect("placeholder recognized", m.is_placeholder, True)
    expect("disabled", m.disabled, True)
    expect("disabled reason", m.disabled_reason, "AI deferred: needs a Clock seam")
    expect("empty body", m.body_empty, True)
    expect("no defects", m.meta.defects, [])


def doc(*lines: str) -> str:
    return "/**\n" + "".join(f" * {l}\n" for l in lines) + " */\n"


L, SD = "tc-agent-mode: characterization, interactive: false", "tc-agent-mode: spec-driven, interactive: false"


def test_defects():
    cases = {
        "characterization without sha": (doc(L) + "@Test void a() {}", "tc-agent-mode characterization without tc-agent-characterizes"),
        "no mode": (doc("tc-agent-note: x") + "@Test void a() {}", "tc-agent metadata without tc-agent-mode"),
        "bad mode": (doc("tc-agent-mode: tdd") + "@Test void a() {}",
                     "tc-agent-mode: 'tdd' is not '<mode>, interactive: true|false' "
                     "with a mode in characterization, spec-driven"),
        "old mode name": (doc("tc-agent-mode: legacy, interactive: false") + "@Test void a() {}",
                          "tc-agent-mode: 'legacy, interactive: false' is not '<mode>, interactive: true|false' "
                          "with a mode in characterization, spec-driven"),
        "mode without interactive": (doc("tc-agent-mode: characterization") + "@Test void a() {}",
                                     "tc-agent-mode: 'characterization' is not '<mode>, interactive: true|false' "
                                     "with a mode in characterization, spec-driven"),
        "bad sha": (doc(L, "tc-agent-characterizes: OrderService") + "@Test void a() {}",
                    "tc-agent-characterizes: 'OrderService' is not <Class>@<sha>"),
        "unknown key": (doc(SD, "tc-agent-foo: x") + "@Test void a() {}",
                        "unknown metadata key 'tc-agent-foo:' (allowed: tc-agent-mode, "
                        "tc-agent-characterizes, tc-agent-deferred, tc-agent-note)"),
        "old marker line": (doc("tc-agent: generated", SD) + "@Test void a() {}",
                            "unknown metadata key 'tc-agent:' (allowed: tc-agent-mode, "
                            "tc-agent-characterizes, tc-agent-deferred, tc-agent-note)"),
        "old interactive line": (doc(SD, "tc-agent-interactive: true") + "@Test void a() {}",
                                 "unknown metadata key 'tc-agent-interactive:' (allowed: tc-agent-mode, "
                                 "tc-agent-characterizes, tc-agent-deferred, tc-agent-note)"),
        "spec-driven with sha": (doc(SD, "tc-agent-characterizes: X@1234567") + "@Test void a() {}",
                                 "tc-agent-mode spec-driven must not carry tc-agent-characterizes"),
        "deferred without Disabled": (doc(SD, "tc-agent-deferred: why") + "@Test void a() {}",
                                      "tc-agent-deferred placeholder without @Disabled / @Ignore"),
        "deferred with body": (doc(SD, "tc-agent-deferred: why") + '@Test @Disabled("AI deferred: why") void a() { x(); }',
                               "tc-agent-deferred placeholder must have an empty body"),
        "Disabled marker without deferred": (doc(SD) + '@Test @Disabled("AI deferred: why") void a() { }',
                                             '@Disabled / @Ignore ("AI deferred: ...") without tc-agent-deferred in the Javadoc'),
    }
    for label, (body, wanted) in cases.items():
        (m,), _ = parse("class T {\n" + body + "\n}\n")
        expect(f"defect: {label}", wanted in m.meta.defects, True)


def test_junit4_ignore_is_a_placeholder():
    body = doc(L, "tc-agent-characterizes: OrderService@29aeef6a", "tc-agent-deferred: needs a seam") \
        + '@Test @Ignore("AI deferred: needs a seam") public void a() {}'
    (m,), _ = parse("class T {\n" + body + "\n}\n")
    expect("JUnit 4 @Ignore counts as disabled", (m.disabled, m.is_placeholder), (True, True))
    expect("no defects", m.meta.defects, [])


def test_old_at_format_is_not_metadata():
    """No backward compatibility: the @-tag draft is just Javadoc, the method reads as human."""
    body = doc("@aiGenerated", "@mode characterization", "@characterizes OrderService@29aeef6a") + "@Test void a() {}"
    (m,), _ = parse("class T {\n" + body + "\n}\n")
    expect("not AI, no defects", (m.meta.ai, m.meta.defects), (False, []))


def test_continuation_stops_at_blank_line():
    body = doc("AI-generated test.", "", SD, "tc-agent-note: first part", "second part", "", "Trailing prose.") \
        + "@Test void a() {}"
    (m,), _ = parse("class T {\n" + body + "\n}\n")
    expect("continuation joined, trailing prose not", m.meta.notes, ["first part second part"])


def test_class_level_tags_are_a_defect():
    text = doc(L) + "class T {\n" + human_test("a") + "}\n"
    methods, defects = parse(text)
    expect("the method stays human", methods[0].meta.ai, False)
    expect("one file-level defect", len(defects), 1)
    expect_true("it names the rule", "never on the class" in defects[0])


def test_human_javadoc_is_not_ai():
    text = "class T {\n/**\n * Checks something.\n * Note: tc-agent-like words in prose are fine.\n * @see Foo\n */\n@Test void a() {}\n}\n"
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
        expect("method a moved", "tc-agent-characterizes: OrderService@4b1c2aa9" in after.split("void a()")[0], True)
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
        original = target.read_bytes()
        target.write_bytes(original.replace(b"\n", b"\r\n"))
        expect("CRLF-only change is not dirty", g.is_dirty(repo.root, target), False)
        target.write_bytes(original)
        repo.change_target()
        expect("dirty after an edit", g.is_dirty(repo.root, target), True)
        repo.git("add", repo.target_path)
        expect("dirty when the edit is only staged", g.is_dirty(repo.root, target), True)
        repo.git("reset", "-q", "--", repo.target_path)
        repo.write("src/main/java/com/acme/NewThing.java", "class NewThing {}\n")
        expect("untracked file is dirty",
               g.is_dirty(repo.root, repo.root / "src/main/java/com/acme/NewThing.java"), True)
        expect("branch", g.current_branch(repo.root), "master")
        repo.git("checkout", "-q", "--detach")
        expect("detached HEAD has no branch", g.current_branch(repo.root), None)


def test_protected_branches():
    def profile_with(repo, value):
        repo.write(".github/agents/tc-agent-project/profile.md", '# p\n\n```json\n{"schema_version": 1%s}\n```\n'
                   % ("" if value is None else ', "protected_branches": ' + value))
        c._PROFILE_CACHE.clear()

    with FixtureRepo() as repo:
        c._PROFILE_CACHE.clear()
        expect("no profile -> master only", c.protected_branches(repo.root), (["master"], "default"))
        profile_with(repo, None)
        expect("no key -> master only", c.protected_branches(repo.root)[0], ["master"])
        profile_with(repo, '["master", "main", "release/*"]')
        expect("list with glob", c.protected_branches(repo.root), (["master", "main", "release/*"], "profile.md"))
        profile_with(repo, "[]")
        expect("empty list -> master, never nothing", c.protected_branches(repo.root)[0], ["master"])
        repo.write("AGENTS.md", "tc-agent-protected-branches: develop\n")
        expect("AGENTS.md is not read any more", c.protected_branches(repo.root)[0], ["master"])
        c._PROFILE_CACHE.clear()


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


def test_verify_refs_catches_name_collisions():
    import json, subprocess
    from tc_testkit import TC
    with FixtureRepo() as repo:
        rel = repo.write_test("OrderServiceTest", ai_test("shouldReturnFalseWhenNumberIsEven", repo.sha()))
        def plan(scenarios, deferred=()):
            body = {"schema_version": 1, "plan_version": 1, "status": "READY",
                    "scenarios": scenarios, "deferred": list(deferred)}
            path = repo.root / "plan.md"
            path.write_text("# p\n\n```json\n" + json.dumps(body) + "\n```\n", encoding="utf-8")
            return subprocess.run([sys.executable, str(TC / "scripts" / "tc_verify_refs.py"), str(path),
                                   "--repo", str(repo.root)], capture_output=True, text=True)
        ev = [{"type": "implementation", "ref": repo.target_path}]
        sc = lambda tc, name, **kw: {"id": tc, "evidence": ev, "implementation_hints":
                                     {"test_method": name, "test_file": rel}, **kw}
        r = plan([sc("TC01", "shouldReturnFalseWhenNumberIsEven")])
        expect("existing name without replaces -> exit 1", (r.returncode, "NAME_COLLISION" in r.stdout), (1, True))
        r = plan([sc("TC01", "shouldReturnFalseWhenNumberIsEven",
                     replaces="OrderServiceTest#shouldReturnFalseWhenNumberIsEven")])
        expect("same name with replaces is fine", r.returncode, 0)
        r = plan([sc("TC01", "shouldA"), sc("TC02", "shouldA")])
        expect("duplicate inside the plan -> exit 1", (r.returncode, "also planned" in r.stdout), (1, True))
        r = plan([sc("TC01", "shouldReportOddWhenNumberIsOdd")])
        expect("unique name passes", r.returncode, 0)


if __name__ == "__main__":
    sys.exit(run_all(globals(), "METADATA_AND_GIT_OK"))
