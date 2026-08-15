#!/usr/bin/env python3
"""Mechanical evidence-ref verifier — closes the fabricated-ref hole.

Every evidence ref in the plan must point at something that actually exists
in the repository. Supported ref shapes:
  ClassName                    -> a file ClassName.java exists
  ClassName#method / Cls.meth  -> file exists AND contains the member name
  path/to/File.java[:line]     -> path exists (line ignored)
  human_decision refs          -> skipped (not repo artifacts)

Exit 0 = all refs verified. Exit 1 = plan contains unverified refs
(INVALID_EVIDENCE) — such a plan must not be passed downstream.

Usage: verify_refs.py <plan.md> [--repo .]
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common" / "scripts"))
from md_payload import load_payload


def find_file(name: str, repo: Path):
    return list(repo.rglob(f"{name}.java"))


def verify(ref: str, etype: str, repo: Path):
    if etype == "human_decision":
        return True, "skipped (human)"
    r = ref.strip()

    # path form
    if r.endswith(".java") or "/" in r or "\\" in r:
        p = r.split(":")[0]
        return (repo / p).exists(), f"path {p}"

    # Class#member or Class.member (member = lowercase start or CONSTANT)
    m = re.match(r"^([A-Z]\w*)#(\w+)$", r)
    if m:
        cls, member = m.group(1), m.group(2)
        files = find_file(cls, repo)
        for f in files:
            if re.search(rf"\b{re.escape(member)}\b",
                         f.read_text(encoding="utf-8", errors="replace")):
                where = f" (of {len(files)} {cls}.java files)" if len(files) > 1 else ""
                return True, f"{cls}.java contains '{member}'{where}"
        return False, f"no {cls}.java containing '{member}'"

    # Dotted ref: Outer.MEMBER, Outer.Inner.MEMBER, Enum.VALUE, etc.
    # First segment = file to find; last segment = symbol to locate inside it.
    m = re.match(r"^([A-Z]\w*)(?:\.[A-Za-z]\w*)+$", r)
    if m:
        cls = m.group(1)
        tail = r.split(".")[-1]
        files = find_file(cls, repo)
        for f in files:
            if re.search(rf"\b{re.escape(tail)}\b",
                         f.read_text(encoding="utf-8", errors="replace")):
                where = f" (of {len(files)} files)" if len(files) > 1 else ""
                return True, f"{cls}.java contains '{tail}'{where}"
        return False, f"no {cls}.java containing '{tail}' (looked in {len(files)} file(s))"

    # bare ClassName
    if re.match(r"^[A-Z]\w*$", r):
        hits = find_file(r, repo)
        if len(hits) > 1:
            return True, f"{r}.java found in {len(hits)} modules (ambiguous)"
        return bool(hits), f"{r}.java {'found' if hits else 'NOT found'}"

    return False, "unrecognized ref shape"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()

    try:
        plan, _ = load_payload(Path(a.plan))
    except (ValueError, Exception) as e:
        print(f"INVALID_ARTIFACT: {e}")
        return 1

    failures = []
    checked = 0
    for section in ("scenarios", "deferred"):
        for sc in plan.get(section) or []:
            for ev in sc.get("evidence") or []:
                checked += 1
                ok, detail = verify(ev.get("ref", ""), ev.get("type", ""), repo)
                mark = "OK " if ok else "FAIL"
                print(f"  [{mark}] {sc.get('id')}: {ev.get('type')}:"
                      f"{ev.get('ref')} — {detail}")
                if not ok:
                    failures.append((sc.get("id"), ev.get("ref")))

    if failures:
        print(f"\nINVALID_EVIDENCE: {len(failures)}/{checked} refs unverified.")
        print("A plan with fabricated/unverifiable refs must not be used.")
        return 1
    print(f"\nALL_REFS_VERIFIED: {checked}/{checked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())