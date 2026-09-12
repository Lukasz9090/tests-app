#!/usr/bin/env python3
"""Deterministic context pack builder for the Test Planner.

Discovers the target's context slice mechanically (no LLM, no tokens):
target source, level-1 dependencies (full), level-2 (signatures only),
existing tests, builders/fixtures, enums. Enforces the context budget in
code and writes a single context-pack.md the agent reads as its ONLY input.

Stdlib only. Usage:
    python build_context.py <ClassName[.method] | path/to/Class.java> [--repo .]
Output:
    .test-agent/context/<TargetSlug>/context-pack.md
"""

import argparse
import re
import sys
from pathlib import Path

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


def find_roots(repo: Path):
    """Maven source/test roots. Maven only — a Gradle repo yields no roots here
    and the planner must stop with UNSUPPORTED_REPOSITORY, because every check
    script downstream drives mvn."""
    src, test = [], []
    # Maven copies the pom into target/classes/META-INF/maven/..., so an
    # unfiltered walk invents modules that live inside the build output.
    poms = (p for p in repo.rglob("pom.xml") if not SKIP_DIRS.intersection(p.parts))
    for pom_dir in {p.parent for p in poms}:
        m, t = pom_dir / "src/main/java", pom_dir / "src/test/java"
        if m.is_dir():
            src.append(m)
        if t.is_dir():
            test.append(t)
    return src or [repo], test


def java_files(roots):
    for r in roots:
        for f in r.rglob("*.java"):
            if not SKIP_DIRS.intersection(f.parts):
                yield f


def find_class_file(name, roots):
    hits = [f for f in java_files(roots) if f.stem == name]
    return hits


_CACHE = {}


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    if not any(p for p in repo.rglob("pom.xml") if not SKIP_DIRS.intersection(p.parts)):
        sys.exit("UNSUPPORTED_REPOSITORY: no pom.xml found. This pipeline is "
                 "Maven-only - every check script drives mvn.")
    src_roots, test_roots = find_roots(repo)

    # --- resolve target ---
    method = None
    tpath = Path(a.target)
    if a.target.endswith(".java") and (repo / tpath).exists():
        target_file = (repo / tpath).resolve()
        cname = target_file.stem
    else:
        parts = a.target.split(".")
        cname = parts[0]
        method = parts[1] if len(parts) > 1 else None
        hits = find_class_file(cname, src_roots)
        if not hits:
            sys.exit(f"TARGET_NOT_FOUND: no {cname}.java under source roots")
        if len(hits) > 1:
            sys.exit("TARGET_AMBIGUOUS:\n" + "\n".join(f"  {h}" for h in hits))
        target_file = hits[0]

    slug = cname + (f".{method}" if method else "")
    target_text = read(target_file)

    all_src = list(java_files(src_roots))
    all_by_name = {f.stem: f for f in all_src}
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

    # --- tests, builders/fixtures, enums ---
    tests = [f for f in java_files(test_roots)
             if cname in f.stem or mentions(read(f), cname)]
    builder_pat = re.compile(r"(Builder|Factory|Fixtures?|TestData|Mother)$")
    wanted = tuple({cname} | l1)                  # one alternation, not one pass per name
    builders = [f for f in java_files(test_roots + src_roots)
                if builder_pat.search(f.stem) and mentions(read(f), *wanted)]
    enums = [all_by_name[d] for d in (l1 | l2)
             if d in all_by_name
             and re.search(rf"\benum\s+{re.escape(d)}\b", read(all_by_name[d]))]

    # --- assemble with budget ---
    out = [f"# Context Pack: {slug}", "",
           f"Repo: {repo}", f"Target file: {target_file.relative_to(repo)}",
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

    # Repo-provided conventions (documentation, NOT behavioral evidence)
    for conv in [repo / ".github" / "copilot-instructions.md",
                 repo / "AGENTS.md",
                 repo / ".test-agent" / "conventions.md"]:
        if conv.exists():
            block = (f"\n## CONVENTIONS (repo-provided, style/naming only — "
                     f"not behavioral evidence): {conv.relative_to(repo)}\n\n"
                     f"{read(conv)}\n")
            if len(block) <= budget:
                out.append(block)
                budget -= len(block)

    # Order = priority, because `add` drops what no longer fits. Existing tests,
    # builders and enums come before the dependency dump: they are the EVIDENCE
    # that keeps a scenario out of `deferred`, so losing them to a class with
    # twelve dependencies is the worst trade this script can make.
    add("TARGET", target_file, target_text)
    for f in sorted(set(tests)):
        add("EXISTING TEST", f, read(f))
    for f in sorted(set(builders)):
        add("BUILDER/FIXTURE", f, read(f))
    for f in sorted(set(enums)):
        add("ENUM", f, read(f))
    for name in sorted(l1):
        f = all_by_name.get(name)
        if f:
            add("DEPENDENCY (level 1, full)", f, read(f))
    for name in sorted(l2):
        f = all_by_name.get(name)
        if f:
            add("DEPENDENCY (level 2, signatures)", f, signatures_only(read(f)))

    out.append("\n## MANIFEST (all files included above)\n")
    for f in [target_file, *[all_by_name[n] for n in sorted(l1 | l2)
                             if n in all_by_name],
              *sorted(set(tests)), *sorted(set(builders)), *sorted(set(enums))]:
        out.append(f"- {f.relative_to(repo)}")
    if notes:
        out.append("\n## NOTES\n")
        out.extend(f"- {n}" for n in notes)

    dest = repo / ".test-agent" / "context" / slug / "context-pack.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"WRITTEN: {dest.relative_to(repo)}")
    print(f"  target={cname} method={method or '-'} "
          f"deps_l1={len(l1)} deps_l2={len(l2)} tests={len(tests)} "
          f"builders={len(builders)} enums={len(enums)} "
          f"size={MAX_TOTAL_CHARS - budget} chars")


if __name__ == "__main__":
    main()
