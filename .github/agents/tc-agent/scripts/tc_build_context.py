#!/usr/bin/env python3
"""Deterministic context pack builder for the Planner and the Generator.

Discovers the target's context slice mechanically (no LLM, no tokens):
target source, level-1 dependencies (full), level-2 (signatures only),
existing tests (with a count of their AI-generated methods and placeholders),
builders/fixtures, enums, and the REPO CONVENTIONS section: the repository's
own instruction files, filtered by `applyTo`. Enforces the context budget in
code and writes a single context-pack.md the agents read as their main input.

Subagents start with a fresh context, so the pack is the reliable channel for
repo instructions; whether the host also injects them is not relied on.

Stdlib only. Usage:
    python tc_build_context.py <ClassName[.method]> --repo . --run <id|latest>
Output:
    .test-agent/runs/<slug>/<run-id>/context-pack.md
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_common as c  # noqa: E402
import tc_javadoc as tj  # noqa: E402

# The planner has to READ this pack, so the budget is bounded by its context
# window, not by disk. ~150k chars is roughly 37k tokens, which leaves room for
# the agent's own reasoning; the old 400k could not be read at all.
MAX_TOTAL_CHARS = 150_000          # hard budget (~37k tokens)
MAX_FILE_CHARS = 40_000            # per-file cap before truncation
SIG_RE = re.compile(
    r"^\s*(?:public|protected)\s+[\w<>\[\],\s?]+\s+\w+\s*\([^;{]*\)", re.M)
IMPORT_RE = re.compile(r"^import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
CLASS_DECL = "(class|interface|enum|record)"
# Build output holds generated and copied sources. A ref that "verifies" against
# target/generated-sources points at a file nobody edits.
SKIP_DIRS = {"target", "build", "out", ".git", ".idea", ".test-agent", "node_modules"}
# ... with one exception: code GENERATED into the build directory (an OpenAPI
# client, MapStruct mappers, protobuf) is real API the target calls, and without
# it every scenario that touches such a type looks unevidenced.
GENERATED_DIRS = ("target/generated-sources", "target/generated-test-sources",
                  "build/generated", "build/generated-sources")
# Imports that need no explanation: nobody defers a test because java.util is
# not in the pack.
STDLIB_PREFIXES = ("java.", "javax.", "jakarta.", "org.junit", "org.mockito",
                   "org.assertj", "org.hamcrest", "lombok.")


def java_files(roots, use_git: bool = True):
    """Shared with the other scripts: git's index when it can answer, else a walk."""
    return c.java_files(roots, use_git=use_git)


_CACHE = {}


def generated_roots(repo: Path) -> list:
    """Build-output directories that hold generated SOURCE, if any exist."""
    out = []
    for rel in GENERATED_DIRS:
        for d in repo.glob(f"**/{rel}"):
            if d.is_dir():
                out.append(d)
    return out


def read(f: Path):
    """Read a file once. Scanning for tests, builders and enums revisits the same
    files many times; without the cache a large repo pays for each visit."""
    key = str(f)
    if key in _CACHE:
        return _CACHE[key]
    try:
        t = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        t = ""
    if len(t) > MAX_FILE_CHARS:
        t = t[:MAX_FILE_CHARS] + f"\n// ... TRUNCATED at {MAX_FILE_CHARS} chars\n"
    _CACHE[key] = t
    return t


def mentions(text: str, *names) -> bool:
    """Does the text use any of these simple names as a whole word?"""
    pattern = "|".join(re.escape(n) for n in names if n)
    return bool(pattern) and re.search(rf"\b(?:{pattern})\b", text) is not None


def signatures_only(text):
    sigs = SIG_RE.findall(text)
    return "\n".join(s.strip() + ";" for s in sigs) or "// (no public signatures found)"


def local_deps(text, all_by_name, own_pkg_files):
    """Project-local classes referenced via imports or same package."""
    deps = set()
    for imp in IMPORT_RE.findall(text):
        simple = imp.rsplit(".", 1)[-1]
        if simple in all_by_name:
            deps.add(simple)
    for f in own_pkg_files:                       # same-package, no import needed
        if f.stem != "package-info" and mentions(text, f.stem):
            deps.add(f.stem)
    return deps


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
PRECEDENCE = ("Precedence, rule by rule: pipeline integrity (tc-contracts.md, "
              "tc-test-conventions.md §A) > these files > agent defaults "
              "(tc-test-conventions.md §B). A rule here that contradicts §A is void.")


def glob_regex(pattern: str) -> re.Pattern:
    """A VS Code / Copilot style glob (`**`, `*`, `?`, `{a,b}`) as a regex."""
    out, i = "", 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if ch == "*":
            out += "[^/]*"
        elif ch == "?":
            out += "[^/]"
        elif ch == "{":
            end = pattern.find("}", i)
            if end == -1:
                out += re.escape(ch)
            else:
                out += "(?:" + "|".join(re.escape(x) for x in pattern[i + 1:end].split(",")) + ")"
                i = end
        else:
            out += re.escape(ch)
        i += 1
    return re.compile("^" + out + "$")


def apply_to(text: str) -> list | None:
    """The `applyTo` globs of an .instructions.md file; None = applies everywhere."""
    front = FRONTMATTER.match(text)
    if not front:
        return None
    for line in front.group(1).splitlines():
        m = re.match(r"^\s*applyTo\s*:\s*(.+?)\s*$", line)
        if m:
            value = m.group(1).strip().strip("'\"")
            globs = [v.strip().strip("'\"") for v in value.split(",") if v.strip()]
            return globs or None
    return None


def instruction_applies(text: str, paths: list) -> tuple[bool, str]:
    globs = apply_to(text)
    if globs is None:
        return True, "no applyTo"
    for pattern in globs:
        rx = glob_regex(pattern)
        for p in paths:
            if rx.match(p):
                return True, f"applyTo: {pattern}"
    return False, f"applyTo: {', '.join(globs)}"


def repo_instructions(repo: Path, relevant_paths: list) -> list:
    """[(path, reason)] of repo instruction files that apply to these paths, in order."""
    found = []
    seen = set()

    def take(path: Path, reason: str):
        key = path.resolve()
        if key in seen or not path.is_file():
            return
        seen.add(key)
        found.append((path, reason))

    take(repo / ".github" / "copilot-instructions.md", "repository-wide")
    idir = repo / ".github" / "instructions"
    if idir.is_dir():
        for f in sorted(idir.rglob("*.instructions.md")):
            ok, why = instruction_applies(f.read_text(encoding="utf-8", errors="replace"), relevant_paths)
            if ok:
                take(f, why)
    take(repo / "AGENTS.md", "repository-wide")
    for extra in c.instruction_paths(repo):
        path = repo / extra
        if path.is_file():
            ok, why = instruction_applies(path.read_text(encoding="utf-8", errors="replace"), relevant_paths)
            if ok:
                take(path, f"tc-project-profile.md instruction_paths ({why})")
    return found


def test_data_files(repo: Path, run: dict) -> list:
    """(path, source) for every file of example business values.

    Only files somebody named: the profile's `test_data_paths` and this run's
    `--test-data`. Nothing is guessed from file names - a file the agent found by
    itself would be data nobody vouched for.
    """
    seen, out = set(), []

    def take(path: Path, source: str) -> None:
        key = str(path.resolve())
        if key in seen or not path.is_file():
            return
        seen.add(key)
        out.append((path, source))

    for rel in c.test_data_paths(repo):
        take(repo / rel, "tc-project-profile.md test_data_paths")
    for rel in run.get("test_data_paths") or []:
        take(repo / rel, "--test-data on this run")
    return out


def test_summary(f: Path) -> str:
    try:
        methods, _ = tj.parse_file(f)
    except OSError:
        return ""
    ai = sum(1 for m in methods if m.meta.ai and not m.is_placeholder)
    ph = sum(1 for m in methods if m.is_placeholder)
    return f"{len(methods)} test methods: {ai} AI-generated, {ph} placeholders, {len(methods) - ai - ph} human"


def _say(message: str) -> None:
    print(f"[tc-agent] {message}", file=sys.stderr, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--run", default="latest")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    try:
        target = c.resolve_target(repo, a.target)
        run_dir = c.run_dir(repo, a.target, a.run)
    except c.TargetError as exc:
        if exc.code == "TARGET_AMBIGUOUS":
            sys.exit(f"TARGET_AMBIGUOUS: {exc}")
        sys.exit(str(exc))
    except c.CheckError as exc:
        sys.exit(f"CANNOT_RUN: {exc}")
    src_roots, test_roots = c.find_roots(repo)
    src_roots = src_roots or [repo]
    target_file, cname, method, slug = target.file, target.cls, target.method, target.slug
    target_text = read(target_file)

    all_src = list(java_files(src_roots))
    gen_roots = generated_roots(repo)
    generated = list(java_files(gen_roots, use_git=False))   # git ignores build output
    all_by_name = {f.stem: f for f in all_src}
    for f in generated:                        # generated code never shadows source
        all_by_name.setdefault(f.stem, f)
    generated_names = {f.stem for f in generated} - {f.stem for f in all_src}
    own_pkg = [f for f in target_file.parent.glob("*.java") if f != target_file]

    # --- deps: level 1 full, level 2 signatures ---
    l1 = local_deps(target_text, all_by_name, own_pkg)
    l2 = set()
    for d in l1:
        f = all_by_name.get(d)
        if f:
            l2 |= local_deps(read(f), all_by_name,
                             [x for x in f.parent.glob("*.java") if x != f])
    l2 -= l1 | {cname}

    _say(f"building the context pack for {cname} (scanning tests, builders and enums)")
    # --- tests, builders/fixtures, enums ---
    # git grep shortlists the files that use these names; reading every test and
    # every builder in a big repo just to ask that question was most of the time
    # this script spent. Without git (no repo, no git) the read is the fallback.
    def uses(names: tuple, pool: list) -> list:
        hits = None
        for name in names:
            found = c.grep_files(repo, name)
            if found is None:
                hits = None
                break
            hits = set() if hits is None else hits
            hits |= {str(f.resolve()) for f in found}
        if hits is None:
            return [f for f in pool if mentions(read(f), *names)]
        return [f for f in pool if str(f.resolve()) in hits]

    test_pool = java_files(test_roots)
    tests = sorted({f for f in test_pool if cname in f.stem} | set(uses((cname,), test_pool)))
    builder_pat = re.compile(r"(Builder|Factory|Fixtures?|TestData|Mother)$")
    wanted = tuple({cname} | l1)                  # one alternation, not one pass per name
    builder_pool = [f for f in java_files(test_roots + src_roots) if builder_pat.search(f.stem)]
    builders = uses(wanted, builder_pool)
    enums = [all_by_name[d] for d in (l1 | l2)
             if d in all_by_name
             and re.search(rf"\benum\s+{re.escape(d)}\b", read(all_by_name[d]))]

    # Types the target imports that this pack could not include: they live in a
    # dependency jar. Naming them beats silence — a role that knows the type
    # exists can look it up; a role that sees nothing calls the scenario
    # unevidenced and writes a placeholder.
    external = sorted({imp for imp in IMPORT_RE.findall(target_text)
                       if not imp.startswith(STDLIB_PREFIXES)
                       and imp.rsplit(".", 1)[-1] not in all_by_name})

    # paths the repo instructions are matched against (applyTo)
    rel_target = target_file.relative_to(repo).as_posix()
    package_dir = target_file.parent.relative_to(repo).as_posix().replace("src/main/java", "src/test/java", 1)
    relevant = [rel_target, f"{package_dir}/{cname}Test.java"]
    relevant += [f.relative_to(repo).as_posix() for f in tests]

    # --- assemble with budget ---
    contract = c.repo_contract(repo, target.module)
    junit = contract.get("junit")
    framework = (f"JUnit {junit}" if junit else
                 "unknown (the pom declares none) - follow the existing test class")
    out = [f"# Context Pack: {slug}", "",
           f"Repo: {repo}", f"TEST FRAMEWORK: {framework} "
           f"(tc-test-conventions.md A0: write the annotations of THIS version)",
           f"Target file: {rel_target}",
           f"Method focus: {method or '(whole class)'}",
           f"Source roots: {[str(r.relative_to(repo)) for r in src_roots]}",
           f"Test roots: {[str(r.relative_to(repo)) for r in test_roots]}", ""]
    budget = MAX_TOTAL_CHARS
    notes = []

    def add(title, f, body):
        nonlocal budget
        block = f"\n## {title}: {f.relative_to(repo)}\n\n```java\n{body}\n```\n"
        if len(block) > budget:
            notes.append(f"BUDGET: omitted {f.relative_to(repo)}")
            return
        out.append(block)
        budget -= len(block)

    # Example business values the repo keeps for exactly this purpose. They go in
    # before the sources: a planner that finds the shape here asks nobody.
    try:
        run_json = c.load_run(run_dir)
    except Exception:                                  # a pack can be built before run.json exists
        run_json = {}
    data_files = test_data_files(repo, run_json)
    if data_files:
        head = ("\n## TEST DATA (repo-provided example business values)\n\n"
                "The shapes real values have in this system. Use them for the values a scenario "
                "needs: take the SHAPE, give each field and each distinct entity its own value of "
                "that shape, and never invent a shape that is not here. Cite the file as evidence "
                "(`fixture`). Ask a human only about a kind that is missing here.\n")
        out.append(head)
        budget -= len(head)
        for f, source in data_files:
            body = f"\n### {f.relative_to(repo).as_posix()} ({source})\n\n{read(f)}\n"
            if len(body) <= budget:
                out.append(body)
                budget -= len(body)
            else:
                notes.append(f"BUDGET: omitted test data {f.relative_to(repo)}")

    # Repo-provided conventions (style only, NOT behavioral evidence)
    instructions = repo_instructions(repo, relevant)
    header = ["\n## REPO CONVENTIONS (repo-provided — style/naming only, NOT behavioral evidence)\n",
              PRECEDENCE, ""]
    if instructions:
        header.append("Sources: " + "; ".join(f"{p.relative_to(repo).as_posix()} ({why})"
                                              for p, why in instructions))
    else:
        header.append("none found — agent defaults (tc-test-conventions.md §B) apply.")
    block = "\n".join(header) + "\n"
    out.append(block)
    budget -= len(block)
    for path, why in instructions:
        body = f"\n### {path.relative_to(repo).as_posix()} ({why})\n\n{read(path)}\n"
        if len(body) <= budget:
            out.append(body)
            budget -= len(body)
        else:
            notes.append(f"BUDGET: omitted repo instructions {path.relative_to(repo)}")

    # Order = priority, because `add` drops what no longer fits. Existing tests,
    # builders and enums come before the dependency dump: they are the EVIDENCE
    # that keeps a scenario out of `deferred`, so losing them to a class with
    # twelve dependencies is the worst trade this script can make.
    add("TARGET", target_file, target_text)
    for f in sorted(set(tests)):
        summary = test_summary(f)
        add(f"EXISTING TEST ({summary})" if summary else "EXISTING TEST", f, read(f))
    for f in sorted(set(builders)):
        add("BUILDER/FIXTURE", f, read(f))
    for f in sorted(set(enums)):
        add("ENUM", f, read(f))
    for name in sorted(l1):
        f = all_by_name.get(name)
        if f:
            add("GENERATED SOURCE (build output, full)" if name in generated_names
                else "DEPENDENCY (level 1, full)", f, read(f))
    for name in sorted(l2):
        f = all_by_name.get(name)
        if f:
            label = "DEPENDENCY (level 2, signatures)"
            if name in generated_names:
                label = "GENERATED SOURCE (build output, signatures)"
            add(label, f, signatures_only(read(f)))

    if external:
        out.append("\n## TYPES FROM DEPENDENCIES (not in this pack)\n")
        out.append("The target imports these; they come from a jar, so no file of "
                   "theirs can be included or cited. This is NOT a reason to defer a "
                   "scenario: build such a value the way the TARGET builds it, or the "
                   "way an existing test does, and cite that line as evidence.\n")
        out.extend(f"- {i}" for i in external)

    out.append("\n## MANIFEST (all files included above)\n")
    for f in [target_file, *[all_by_name[n] for n in sorted(l1 | l2)
                             if n in all_by_name],
              *sorted(set(tests)), *sorted(set(builders)), *sorted(set(enums))]:
        out.append(f"- {f.relative_to(repo)}")
    if notes:
        out.append("\n## NOTES\n")
        out.extend(f"- {n}" for n in notes)

    _say(f"context pack: {len(tests)} test file(s), {len(builders)} builder(s), "
         f"{len(l1)} dependency file(s)")
    dest = run_dir / "context-pack.md"
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"WRITTEN: {dest.relative_to(repo).as_posix()}")
    print(f"  target={cname} method={method or '-'} "
          f"deps_l1={len(l1)} deps_l2={len(l2)} generated={len(generated_names & (l1 | l2))} "
          f"external={len(external)} tests={len(tests)} "
          f"builders={len(builders)} enums={len(enums)} "
          f"instructions={len(instructions)} size={MAX_TOTAL_CHARS - budget} chars")


if __name__ == "__main__":
    main()
