#!/usr/bin/env python3
"""Deterministic evidence-strength classifier for a test plan (embedded JSON).

Strength is NEVER estimated by the LLM. This script reads each scenario's
evidence and labels it strong / medium / weak from fixed rules, then (with
--write) stores `evidence_strength` on every scenario and deferred entry. That
label DRIVES Phase 5: a `weak` scenario moves to `deferred`, the rest stay.

It used to also compute a numeric `confidence` (a noisy-OR over per-type
weights) that nothing downstream ever read. That number is gone; only the
categorical label, which actually decides, remains.

Usage:
    tc_evidence_strength.py <plan.md>            # print the per-scenario table
    tc_evidence_strength.py <plan.md> --write    # also write the labels into the file
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tc_md_payload import load_payload, save_payload

# Exactly the evidence types tc-test-plan.schema.json allows.
VALID_TYPES = {
    "human_decision", "existing_test", "builder", "fixture",
    "usage", "implementation", "enum", "db_constraint", "api_schema",
}
# A single entry of one of these substantiates a value independently.
STRONG_TYPES = {"human_decision", "existing_test"}
# Each is worth a point, but one alone is not enough to reach 'medium'.
MEDIUM_POOL = {"usage", "enum", "db_constraint", "api_schema"}


def strength(evidence_list):
    """Categorical rules, first match wins. Distinct = unique (type, ref)."""
    entries = {(e.get("type"), e.get("ref")) for e in evidence_list or []
               if e.get("type") in VALID_TYPES}
    types = {t for t, _ in entries}
    if types & STRONG_TYPES:
        return "strong"
    if types & {"builder", "fixture"}:
        return "strong" if len(types) >= 2 else "medium"
    # The source of the code under test: on its own it is enough to characterize
    # current behaviour (legacy/characterization), so it is never weak by itself.
    if "implementation" in types:
        return "medium"
    pool = [(t, r) for t, r in entries if t in MEDIUM_POOL]
    pool_types = {t for t, _ in pool}
    if len(pool_types) >= 2 or sum(1 for t, _ in pool if t == "usage") >= 2:
        return "medium"
    return "weak"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    write = "--write" in sys.argv[2:]

    try:
        plan, original = load_payload(path)
    except (OSError, ValueError) as e:      # not bare Exception: a bug here must not
        sys.exit(f"ERROR: {e}")             # be reported as a malformed artifact
    if not isinstance(plan, dict):
        sys.exit(f"Not a JSON object: {path}")

    rows = []
    for section in ("scenarios", "deferred"):
        for sc in plan.get(section) or []:
            cat = strength(sc.get("evidence"))
            sc["evidence_strength"] = cat    # decision-driving: weak -> deferred
            sc.pop("confidence", None)       # drop any stale numeric field
            rows.append((sc.get("id", "?"), section, cat, len(sc.get("evidence") or [])))

    if write:
        save_payload(path, plan, original)

    print(f"{'id':6} {'section':10} {'strength':9} evidence")
    for rid, section, cat, n in rows:
        print(f"{rid:6} {section:10} {cat:9} {n}")
    if write:
        print(f"\nWritten to {path}")


if __name__ == "__main__":
    main()
