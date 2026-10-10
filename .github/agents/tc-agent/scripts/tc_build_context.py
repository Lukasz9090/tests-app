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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_common as c  # noqa: E402
import tc_javadoc as tj  # noqa: E402

# The planner has to READ this pack, so the budget is bounded by its context
# window, not by disk. ~150k chars is roughly 37k tokens, which leaves room for
# the agent's own reasoning; the old 400k could not be read at all.
MAX_TOTAL_CHARS = 150_000          # hard budget (~37k tokens)
MAX_FILE_CHARS = 40_000            # per-file cap before truncation
SPEC_BUDGET = 30_000               # the spec of a spec-driven run, before the sources
SIG_RE = re.compile(
    r"^\s*(?:public|protected)\s+[\w<>\[\],\s?]+\s+\w+\s*\([^;{]*\)", re.M)
IMPORT_RE = re.compile(r"^import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
CLASS_DECL = "(class|interface|enum|record)"
# ... with one exception: code GENERATED into the build directory (an OpenAPI
# client, MapStruct mappers, protobuf) is real API the target calls, and without
# it every scenario that touches such a type looks unevidenced.
GENERATED_DIRS = ("target/generated-sources", "target/generated-test-sources",
                  "build/generated", "build/generated-sources")
# Imports that need no explanation: nobody defers a test because java.util is
# not in the pack.
STDLIB_PREFIXES = ("java.", "javax.", "jakarta.", "org.junit", "org.mockito",
                   "org.assertj", "org.hamcrest", "lombok.")


_CACHE = {}


def generated_roots(repo: Path, modules) -> list:
    """Build-output directories that hold generated SOURCE, if any exist.

    Checked per module, never globbed: `repo.glob("**/target/generated-sources")`
    walks every target/ in the reactor - thousands of class files per module -
    and in a big repo that alone took minutes.
    """
    out = []
    for module in modules:
        for rel in GENERATED_DIRS:
            d = module / rel
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


def numbered(text: str) -> str:
    """The text with each line prefixed by its line number in the FILE.

    Roles cite evidence as `path:NN`. Without the file's own numbers they count
    lines of the pack instead, and every ref lands as far off as the sections
    above the block are long.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}}  {line}" for i, line in enumerate(lines, 1))


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
        if f.stem != "package-info" and c.mentions(text, f.stem):
            deps.add(f.stem)
    return deps


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
PRECEDENCE = ("Precedence, rule by rule: pipeline integrity (contracts.md, conventions.md §A, "
              "junit4.md, the mode files) > these files > agent defaults (conventions.md §B). "
              "A rule here that contradicts §A is void.")


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

    conventions = c.project_file(repo, "conventions.md")
    if conventions:
        take(conventions, "project conventions")
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
                take(path, f"profile.md instruction_paths ({why})")
    return found


def test_data_files(repo: Path, run: dict) -> list:
    """(path, source) for every file of example business values.

    Only files somebody put there on purpose: the project's `test-data.md`, the
    profile's `test_data_paths` and this run's `--test-data`. Nothing is guessed
    from file names - a file the agent found by itself would be data nobody
    vouched for.
    """
    seen, out = set(), []

    def take(path: Path, source: str) -> None:
        key = str(path.resolve())
        if key in seen or not path.is_file():
            return
        seen.add(key)
        out.append((path, source))

    project_data = c.project_file(repo, "test-data.md")
    if project_data:
        take(project_data, "project test-data.md")
    for rel in c.test_data_paths(repo):
        take(repo / rel, "profile.md test_data_paths")
    for rel in run.get("test_data_paths") or []:
        take(repo / rel, "--test-data on this run")
    return out


# --- DATA EXAMPLES: how the existing tests fill the fields this target uses ---
# Only value-like types: an id, a code or an amount has a shape worth copying;
# a collection or a domain object does not.
VALUE_TYPES = {"String", "CharSequence", "Long", "long", "Integer", "int", "Short", "short",
               "UUID", "BigDecimal", "BigInteger"}
# Too generic to tell one concept from another: `id` of what, `name` of what.
GENERIC_NAMES = {"id", "name", "value", "key", "type", "code", "data", "text", "result", "status"}
FIELD_DECL = re.compile(r"^\s*(?:(?:private|protected|public|final|static)\s+)*([\w.<>\[\]]+)\s+([a-z]\w*)\s*(?:=[^;]*)?;",
                        re.M)
RECORD_DECL = re.compile(r"\brecord\s+\w+\s*\(([^)]*)\)")
PUBLIC_METHOD = re.compile(r"^\s*public\s+(?:static\s+)?[\w<>\[\],.?\s]+?\s+\w+\s*\(([^)]*)\)", re.M)
LITERAL = re.compile(r'"[^"\n]+"|\b\d{2,}L?\b')
ASSERTION = re.compile(r"\b(?:assert\w*|isEqualTo|verify)\b")
EXAMPLES_PER_NAME, MAX_NAMES, DATA_BUDGET = 3, 25, 6000


def _params(decl: str) -> list:
    """(type, name) pairs of a parameter list, commas inside generics respected."""
    parts, depth, current = [], 0, ""
    for ch in decl:
        depth += ch == "<"
        depth -= ch == ">"
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    out = []
    for part in parts:
        tokens = re.sub(r"@\w+(?:\([^)]*\))?|\bfinal\b", " ", part).split()
        if len(tokens) >= 2:
            out.append((tokens[-2], tokens[-1]))
    return out


def value_field_names(target_text: str, dep_texts: list) -> list:
    """Names of value-typed parameters of the target's public methods and of the
    fields / record components of the classes it uses directly."""
    pairs = []
    for m in PUBLIC_METHOD.finditer(target_text):
        pairs += _params(m.group(1))
    for text in dep_texts:
        pairs += [(t, n) for t, n in FIELD_DECL.findall(text)]
        for m in RECORD_DECL.finditer(text):
            pairs += _params(m.group(1))
    names = []
    for typ, name in pairs:
        if (typ.split("<")[0].rsplit(".", 1)[-1] in VALUE_TYPES and len(name) > 2
                and name.lower() not in GENERIC_NAMES and name not in names):
            names.append(name)
    return names[:MAX_NAMES]


def data_examples(repo: Path, names: list, roots: list) -> str | None:
    """Lines anywhere in the test tree that put a literal into one of these names.

    One `git grep` for all names. Assertion lines are left out: they show what the
    code returned, not what a real input looks like. None when git cannot answer
    or nothing was found.
    """
    if not names or not roots:
        return None
    paths = []
    for root in roots:
        paths.append(root.relative_to(repo).as_posix())
        resources = root.parent / "resources"
        if resources.is_dir():
            paths.append(resources.relative_to(repo).as_posix())
    code, out = c.run(["git", "-C", str(repo), "grep", "-n", "-I", "--untracked", "-w", "-E",
                       "(" + "|".join(re.escape(n) for n in names) + ")", "--", *paths], repo)
    if code != 0:
        return None
    found = {n: [] for n in names}
    for line in sorted(out.splitlines()):
        parts = line.split(":", 2)
        if len(parts) < 3 or ASSERTION.search(parts[2]) or not LITERAL.search(parts[2]):
            continue
        path, number, content = parts[0], parts[1], parts[2].strip()
        for name in names:
            picked = found[name]
            if len(picked) >= EXAMPLES_PER_NAME or not re.search(rf"\b{re.escape(name)}\b", content):
                continue
            literal = LITERAL.search(content).group(0)
            if all(literal != lit for _, _, _, lit in picked):
                picked.append((path, number, content[:140], literal))
    blocks, size = [], 0
    for name in names:
        if not found[name]:
            continue
        width = max(len(f"{p}:{n}") for p, n, _, _ in found[name])
        block = name + "\n" + "".join(f"  {(p + ':' + n).ljust(width)}   {text}\n"
                                       for p, n, text, _ in found[name])
        if size + len(block) > DATA_BUDGET:
            break
        blocks.append(block)
        size += len(block)
    if not blocks:
        return None
    return ("\n## DATA EXAMPLES (lines from existing tests that set the fields this target uses)\n\n"
            "From the WHOLE test tree, not only this target's tests. A value for one of these "
            "fields takes the shape shown here (conventions.md §A4, source 3) and cites the line "
            "as `existing_test` evidence.\n\n" + "\n".join(blocks))


def test_summary(f: Path) -> str:
    try:
        methods, _ = tj.parse_file(f)
    except OSError:
        return ""
    ai = sum(1 for m in methods if m.meta.ai and not m.is_placeholder)
    ph = sum(1 for m in methods if m.is_placeholder)
    return f"{len(methods)} test methods: {ai} AI-generated, {ph} placeholders, {len(methods) - ai - ph} human"


_STARTED = time.monotonic()


def _say(message: str) -> None:
    """Progress with elapsed seconds: a pack that takes minutes must show where."""
    print(f"[tc-agent] +{time.monotonic() - _STARTED:5.1f}s {message}",
          file=sys.stderr, flush=True)


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

    # Module directories: the parent of src/main/java, plus the repo root.
    modules = {repo}
    for root in src_roots + test_roots:
        parts = root.parts
        if "src" in parts:
            modules.add(Path(*parts[:parts.index("src")]))
    _say(f"{len(src_roots)} source root(s), {len(test_roots)} test root(s)")
    all_src = list(c.java_files(src_roots))
    gen_roots = generated_roots(repo, sorted(modules))
    generated = list(c.java_files(gen_roots, use_git=False))   # git ignores build output
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

    _say(f"{len(all_src)} source file(s) indexed; {len(l1)} direct dependency file(s)")
    # --- tests, builders/fixtures, enums ---
    # git grep shortlists the files that use these names; reading every test and
    # every builder in a big repo just to ask that question was most of the time
    # this script spent. Without git (no repo, no git) the read is the fallback.
    def uses(names, pool: list) -> list:
        """Files of `pool` that use any of these names - one git grep for all."""
        found = c.grep_files(repo, list(names))
        if found is None:                          # no git: read the pool instead
            return [f for f in pool if c.mentions(read(f), *names)]
        hits = {str(f) for f in found}
        return [f for f in pool if str(f) in hits]

    test_pool = c.java_files(test_roots)
    _say(f"{len(test_pool)} test file(s) in scope; asking git which ones use {cname}")
    tests = sorted({f for f in test_pool if cname in f.stem} | set(uses([cname], test_pool)))
    builder_pat = re.compile(r"(Builder|Factory|Fixtures?|TestData|Mother)$")
    # One name per dependency would be one git grep per dependency; the target
    # plus its level-1 deps is a single alternation, and 25 names is plenty.
    wanted = [cname] + sorted(l1)[:24]
    builder_pool = [f for f in test_pool + all_src if builder_pat.search(f.stem)]
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
    source = contract.get("junit_source")
    framework = (f"JUnit {junit}" + (f" - from {source}" if source else "") if junit else
                 "unknown (nothing in the poms or the module's tests) - follow the existing "
                 "test class")
    if contract.get("junit_mixed"):
        framework += "; the module's tests use BOTH versions - match the class you extend"
    out = [f"# Context Pack: {slug}", "",
           f"Repo: {repo}", f"TEST FRAMEWORK: {framework} "
           f"(conventions.md A0: write the annotations of THIS version)",
           f"Target file: {rel_target}",
           f"Method focus: {method or '(whole class)'}",
           f"Source roots: {[str(r.relative_to(repo)) for r in src_roots]}",
           f"Test roots: {[str(r.relative_to(repo)) for r in test_roots]}",
           "LINE NUMBERS: every source block below shows the FILE's own line number in its "
           "left column - cite refs as `path:NN` from that column, never by counting lines "
           "of this pack. Signature-only blocks have no numbers: open the file for a ref.", ""]
    budget = MAX_TOTAL_CHARS
    notes = []
    included = []

    def block_of(title, f, body, with_numbers=True):
        # ```text, not ```java: with the line-number column the block is no longer
        # valid Java, and a fence must hold what its language says.
        body = numbered(body) if with_numbers else body
        return f"\n## {title}: {f.relative_to(repo)}\n\n```text\n{body}\n```\n"

    def add(title, f, body, with_numbers=True):
        nonlocal budget
        block = block_of(title, f, body, with_numbers)
        if len(block) > budget:
            notes.append(f"BUDGET: omitted {f.relative_to(repo)}")
            return
        out.append(block)
        included.append(f)
        budget -= len(block)

    try:
        run_json = c.load_run(run_dir)
    except Exception:                                  # a pack can be built before run.json exists
        run_json = {}

    # The target and the spec are what the pack exists for: their room is reserved first.
    target_block = block_of("TARGET", target_file, target_text)
    spec_rel = run_json.get("spec")
    spec_file = (repo / spec_rel) if spec_rel else None
    spec_block = ""
    if spec_file and spec_file.is_file():
        text = spec_file.read_text(encoding="utf-8", errors="replace")
        if len(text) > SPEC_BUDGET:
            text = text[:SPEC_BUDGET] + f"\n... TRUNCATED at {SPEC_BUDGET} chars - read the rest of the file\n"
        spec_block = (f"\n## SPEC: {spec_rel} (the oracle of this spec-driven run)\n\n"
                      f"Cite requirements as `tc-agent-spec: {spec_rel}#<id or heading>`.\n\n"
                      f"```text\n{numbered(text)}\n```\n")
    budget -= len(target_block) + len(spec_block)

    # Example business values the repo keeps for exactly this purpose. They go in
    # before the sources: a planner that finds the shape here asks nobody.
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

    names = value_field_names(target_text, [read(all_by_name[n]) for n in sorted(l1) if n in all_by_name])
    examples = data_examples(repo, names, test_roots)
    _say(f"data examples: {len(names)} field name(s) asked, "
         f"{examples.count(chr(10) + '  ') if examples else 0} line(s) found")
    if examples and len(examples) <= budget:
        out.append(examples)
        budget -= len(examples)

    # Repo-provided conventions (style only, NOT behavioral evidence)
    instructions = repo_instructions(repo, relevant)
    header = ["\n## REPO CONVENTIONS (repo-provided — style/naming only, NOT behavioral evidence)\n",
              PRECEDENCE, ""]
    if instructions:
        header.append("Sources: " + "; ".join(f"{p.relative_to(repo).as_posix()} ({why})"
                                              for p, why in instructions))
    else:
        header.append("none found — agent defaults (conventions.md §B) apply.")
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
    out.append(spec_block + target_block)
    included.append(target_file)
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
            add(label, f, signatures_only(read(f)), with_numbers=False)

    if external:
        out.append("\n## TYPES FROM DEPENDENCIES (not in this pack)\n")
        out.append("The target imports these; they come from a jar, so no file of "
                   "theirs can be included or cited. This is NOT a reason to defer a "
                   "scenario: build such a value the way the TARGET builds it, or the "
                   "way an existing test does, and cite that line as evidence.\n")
        out.extend(f"- {i}" for i in external)

    out.append("\n## MANIFEST (all files included above)\n")
    out.extend(f"- {f.relative_to(repo)}" for f in included)
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
