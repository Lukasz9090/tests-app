#!/usr/bin/env python3
"""Deterministic confidence calculator for test-plan.md (embedded JSON payload) (decision D4).

Confidence is NEVER estimated by the LLM. It is computed here from evidence
weights using a noisy-OR combination:

    confidence = 1 - PRODUCT(1 - weight_i)   over unique (type, ref) evidence

Duplicate (type, ref) pairs count once. Result rounded to 2 decimals.

Usage:
    compute_confidence.py <plan.md>            # print per-scenario table
    compute_confidence.py <plan.md> --write    # also write values into file
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common" / "scripts"))
from md_payload import load_payload, save_payload

# Evidence weights (see architecture doc, section 8).
# human_decision > existing_test > builder/fixture > usage > enum/constraint
WEIGHTS = {
    "human_decision": 0.95,
    "existing_test": 0.80,
    "runtime_observation": 0.75,
    "dynamic_invariant": 0.70,
    "builder": 0.60,
    "fixture": 0.60,
    "usage": 0.40,
    "api_schema": 0.35,
    "db_constraint": 0.25,
    "enum": 0.25,
}


STRONG_TYPES = {"human_decision", "existing_test", "runtime_observation"}
MEDIUM_POOL = {"usage", "api_schema", "db_constraint", "enum", "dynamic_invariant"}


def strength(evidence_list):
    """Calibrated categorical rules (validated on real runs) — DECISION-DRIVING.
    Applied in order, first match wins. Distinct = unique (type, ref)."""
    entries = {(e.get("type"), e.get("ref")) for e in evidence_list or []
               if e.get("type") in WEIGHTS}
    types = {t for t, _ in entries}
    if types & STRONG_TYPES:
        return "strong"
    has_builder = bool(types & {"builder", "fixture"})
    if has_builder and len(types) >= 2:
        return "strong"
    if has_builder:
        return "medium"
    pool = [(t, r) for t, r in entries if t in MEDIUM_POOL]
    pool_types = {t for t, _ in pool}
    if len(pool_types) >= 2 or len([1 for t, _ in pool if t == "usage"]) >= 2:
        return "medium"
    return "weak"


def score(evidence_list):
    seen = set()
    remaining = 1.0
    for ev in evidence_list or []:
        etype = ev.get("type")
        key = (etype, ev.get("ref"))
        if etype not in WEIGHTS or key in seen:
            continue
        seen.add(key)
        remaining *= 1.0 - WEIGHTS[etype]
    return round(1.0 - remaining, 2)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    write = "--write" in sys.argv[2:]

    try:
        plan, original = load_payload(path)
    except (ValueError, Exception) as e:
        sys.exit(f"ERROR: {e}")
    if not isinstance(plan, dict):
        sys.exit(f"Not a JSON object: {path}")

    rows = []
    for section in ("scenarios", "deferred"):
        for sc in plan.get(section) or []:
            conf = score(sc.get("evidence"))
            cat = strength(sc.get("evidence"))
            sc["confidence"] = conf          # informational
            sc["evidence_strength"] = cat    # decision-driving: weak -> deferred
            rows.append((sc.get("id", "?"), section, cat, conf,
                         len(sc.get("evidence") or [])))

    if write:
        save_payload(path, plan, original)

    print(f"{'id':6} {'section':10} {'strength':9} {'confidence':10} evidence")
    for rid, section, cat, conf, n in rows:
        print(f"{rid:6} {section:10} {cat:9} {conf:<10} {n}")
    if write:
        print(f"\nWritten to {path}")


if __name__ == "__main__":
    main()
