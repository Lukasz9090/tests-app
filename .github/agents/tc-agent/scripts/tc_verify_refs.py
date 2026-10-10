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
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_common as c  # noqa: E402
from tc_md_payload import load_payload  # noqa: E402

LINE_SUFFIX = re.compile(r":(\d+)(?:-(\d+))?$")
# `path/File.ext[:NN[-MM]]` - checked whatever the evidence type; a human's answer is not one.
PATH_REF = re.compile(r"^[\w.$/\\-]+\.\w+(?::\d+(?:-\d+)?)?$")


class Repo:
    """One walk of the repository, then pure lookups.

    The previous version ran `rglob` for every ref, which is O(refs x repo) and
    dominated the runtime on anything larger than a sample project.
    """

    def __init__(self, root: Path):
        self.root = root
        self.by_stem = {}
        for path in c.java_files([root]):
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
    if c.SKIP_DIRS.intersection(Path(rel).parts):
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
    r = (ref or "").strip()
    if etype == "human_decision" and not PATH_REF.match(r):
        return True, "skipped (a human's answer)"
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
    run_json = Path(a.plan).resolve().parent / "run.json"
    spec = json.loads(run_json.read_text(encoding="utf-8")).get("spec") if run_json.is_file() else None
    spec_driven = plan.get("mode") == "spec-driven"
    failures, no_spec = [], []
    checked = 0
    for section in ("scenarios", "deferred"):
        for sc in plan.get(section) or []:
            refs = [(ev.get("type", ""), ev.get("ref", "")) for ev in sc.get("evidence") or []]
            refs += [("data", d["ref"]) for d in (sc.get("data") or {}).values()
                     if isinstance(d, dict) and isinstance(d.get("ref"), str) and PATH_REF.match(d["ref"])]
            for etype, ref in refs:
                checked += 1
                ok, detail = verify(ref, etype, repo)
                print(f"  [{'OK ' if ok else 'FAIL'}] {sc.get('id')}: {etype}:{ref} — {detail}")
                if not ok:
                    failures.append((sc.get("id"), ref))
            cites_spec = spec and any(LINE_SUFFIX.sub("", r).replace("\\", "/") == spec.replace("\\", "/")
                                      for _, r in refs)
            if spec_driven and not cites_spec:
                no_spec.append(sc.get("id"))

    collisions = name_collisions(plan, repo.root)
    for c in collisions:
        print(f"  [FAIL] {c}")

    if failures:
        print(f"\nINVALID_EVIDENCE: {len(failures)}/{checked} refs unverified.")
        print("A plan with fabricated or unverifiable refs must not be used.")
    if collisions:
        print(f"\nNAME_COLLISION: {len(collisions)} planned test method name(s) already exist "
              f"or repeat inside the plan. Choose names that are unique in the test class "
              f"(conventions.md §B1: the outcome names the operation, e.g. "
              f"shouldReportOddWhenNumberIsOdd vs shouldReportEvenWhenNumberIsEven), or set "
              f"`replaces` when you really mean to rewrite that method.")
    if no_spec:
        print(f"\nSPEC_REF_MISSING: {', '.join(map(str, no_spec))} cite no line of the spec "
              f"({spec or 'run.json names none'}). A spec-driven test comes only from the spec: "
              f"cite its requirement, or remove the scenario.")
    if failures or collisions or no_spec:
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
