#!/usr/bin/env python3
"""Mechanical evidence-ref verifier — closes the fabricated-ref hole.

Every evidence ref in the plan must point at something that really exists in the
repository. Supported shapes:
  ClassName                    -> a file ClassName.java exists
  ClassName#method / Cls.meth  -> file exists AND contains the member name
  path/to/File.java[:line]     -> path exists AND is long enough for the line
  human_decision refs          -> skipped (not repo artifacts)

Line numbers are checked, not ignored: `File.java:147` on a 90-line file is a
fabricated ref, and the Reviewer attributes uncovered branches and surviving
mutants through exactly those numbers.

Exit 0 = all refs verified. Exit 1 = the plan contains unverified refs
(INVALID_EVIDENCE) and must not be passed downstream. Exit 2 = cannot run.

Usage: tc_verify_refs.py <plan.md> [--repo .]
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tc_md_payload import load_payload  # noqa: E402

# Build output holds generated and copied sources; a ref that resolves there
# points at a file nobody edits.
SKIP_DIRS = {"target", "build", "out", ".git", ".idea", ".test-agent", "node_modules"}
LINE_SUFFIX = re.compile(r":(\d+)(?:-(\d+))?$")


class Repo:
    """One walk of the repository, then pure lookups.

    The previous version ran `rglob` for every ref, which is O(refs x repo) and
    dominated the runtime on anything larger than a sample project.
    """

    def __init__(self, root: Path):
        self.root = root
        self.by_stem = {}
        for path in root.rglob("*.java"):
            if SKIP_DIRS.intersection(path.relative_to(root).parts):
                continue
            self.by_stem.setdefault(path.stem, []).append(path)
        self._text = {}

    def files(self, simple_name: str) -> list:
        return self.by_stem.get(simple_name, [])

    def text(self, path: Path) -> str:
        key = str(path)
        if key not in self._text:
            try:
                self._text[key] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._text[key] = ""
        return self._text[key]

    def contains(self, path: Path, member: str) -> bool:
        return re.search(rf"\b{re.escape(member)}\b", self.text(path)) is not None

    def line_count(self, path: Path) -> int:
        return len(self.text(path).splitlines())


def verify_path(ref: str, repo: Repo):
    """`path/to/File.java`, optionally with `:NN` or `:NN-MM`."""
    match = LINE_SUFFIX.search(ref)
    rel = ref[: match.start()] if match else ref
    path = repo.root / rel
    if SKIP_DIRS.intersection(Path(rel).parts):
        return False, f"{rel} is under build output, not source"
    if not path.exists():
        return False, f"no such path: {rel}"
    if not match:
        return True, f"path {rel}"

    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    total = repo.line_count(path)
    if start < 1 or end < start:
        return False, f"{rel}: line range {match.group(0)[1:]} is not a range"
    if end > total:
        return False, f"{rel} has {total} lines, ref points at {end}"
    return True, f"{rel}:{match.group(0)[1:]} (of {total} lines)"


def verify_member(cls: str, member: str, repo: Repo, shape: str):
    files = repo.files(cls)
    for f in files:
        if repo.contains(f, member):
            where = f" (of {len(files)} {cls}.java files)" if len(files) > 1 else ""
            return True, f"{cls}.java contains '{member}'{where}"
    if not files:
        return False, f"no {cls}.java anywhere in the repository"
    return False, f"no {cls}.java containing '{member}' (looked in {len(files)} file(s), {shape})"


def verify(ref: str, etype: str, repo: Repo):
    if etype == "human_decision":
        return True, "skipped (human)"
    r = (ref or "").strip()
    if not r:
        return False, "empty ref"

    if r.endswith(".java") or "/" in r or "\\" in r or LINE_SUFFIX.search(r):
        return verify_path(r, repo)

    # Class#member
    m = re.match(r"^([A-Z]\w*)#(\w+)$", r)
    if m:
        return verify_member(m.group(1), m.group(2), repo, "Class#member")

    # Dotted: Outer.MEMBER, Outer.Inner.MEMBER, Enum.VALUE
    m = re.match(r"^([A-Z]\w*)(?:\.[A-Za-z]\w*)+$", r)
    if m:
        return verify_member(m.group(1), r.split(".")[-1], repo, "dotted ref")

    # bare ClassName
    if re.match(r"^[A-Z]\w*$", r):
        hits = repo.files(r)
        if len(hits) > 1:
            return True, f"{r}.java found in {len(hits)} modules (ambiguous)"
        return bool(hits), f"{r}.java {'found' if hits else 'NOT found'}"

    return False, "unrecognized ref shape"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plan")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()

    try:
        plan, _ = load_payload(Path(a.plan))
    except (OSError, ValueError) as exc:
        print(f"INVALID_ARTIFACT: {exc}")
        return 2

    repo = Repo(Path(a.repo).resolve())
    failures = []
    checked = 0
    for section in ("scenarios", "deferred"):
        for sc in plan.get(section) or []:
            for ev in sc.get("evidence") or []:
                checked += 1
                ok, detail = verify(ev.get("ref", ""), ev.get("type", ""), repo)
                print(f"  [{'OK ' if ok else 'FAIL'}] {sc.get('id')}: {ev.get('type')}:"
                      f"{ev.get('ref')} — {detail}")
                if not ok:
                    failures.append((sc.get("id"), ev.get("ref")))

    collisions = name_collisions(plan, repo.root)
    for c in collisions:
        print(f"  [FAIL] {c}")

    if failures:
        print(f"\nINVALID_EVIDENCE: {len(failures)}/{checked} refs unverified.")
        print("A plan with fabricated or unverifiable refs must not be used.")
    if collisions:
        print(f"\nNAME_COLLISION: {len(collisions)} planned test method name(s) already exist "
              f"or repeat inside the plan. Choose names that are unique in the test class "
              f"(tc-test-conventions.md §B1: the outcome names the operation, e.g. "
              f"shouldReportOddWhenNumberIsOdd vs shouldReportEvenWhenNumberIsEven), or set "
              f"`replaces` when you really mean to rewrite that method.")
    if failures or collisions:
        return 1
    print(f"\nALL_REFS_VERIFIED: {checked}/{checked}; test method names unique")
    return 0


def name_collisions(plan: dict, root: Path) -> list:
    """Planned method names that already exist in their test file, or repeat in the plan.

    A name that exists is fine only when the entry `replaces` exactly that method.
    """
    try:
        import tc_javadoc as tj
    except ImportError:
        return []
    out, seen, cache = [], {}, {}
    entries = [(sc, (sc.get("implementation_hints") or {}).get("test_method"),
                (sc.get("implementation_hints") or {}).get("test_file")) for sc in plan.get("scenarios") or []]
    entries += [(d, d.get("placeholder_method"), d.get("test_file")) for d in plan.get("deferred") or []]
    for entry, name, test_file in entries:
        if not name:
            continue
        key = (test_file or "", name)
        if key in seen:
            out.append(f"{entry.get('id')}: method name {name} is also planned for {seen[key]}")
        seen[key] = entry.get("id")
        if not test_file:
            continue
        path = root / test_file
        if not path.is_file():
            continue
        if test_file not in cache:
            try:
                cache[test_file] = {m.name: m.key for m in tj.parse_file(path)[0]}
            except OSError:
                cache[test_file] = {}
        existing = cache[test_file].get(name)
        if existing and entry.get("replaces") != existing:
            out.append(f"{entry.get('id')}: {name} already exists in {test_file} ({existing}) "
                       f"and the entry does not replace it")
    return out


if __name__ == "__main__":
    sys.exit(main())
