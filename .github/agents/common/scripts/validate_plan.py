#!/usr/bin/env python3
"""Hard schema validation of test-plan.md (embedded JSON payload) (decision D12).

An artifact that fails validation is INVALID_ARTIFACT and must never be
passed to a downstream LLM agent. Exit code 0 = valid, 1 = invalid.

Usage:
    validate_plan.py <artifact.md> <schema.json>
Generic: validates the json payload of any md-container artifact.
"""

import json
import sys

from md_payload import load_payload
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("Missing dependency: pip install jsonschema")




def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if len(sys.argv) < 3:
        sys.exit("Usage: validate_plan.py <artifact.md> <schema.json>")
    plan_path = Path(sys.argv[1])
    schema_path = Path(sys.argv[2])

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        plan, _ = load_payload(plan_path)
    except ValueError as e:
        print(f"INVALID_ARTIFACT: {plan_path}")
        print(f"  - {e}")
        return 1

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(plan), key=lambda e: list(e.path))

    if not errors:
        print(f"VALID: {plan_path} (schema_version="
              f"{plan.get('schema_version')}, status={plan.get('status')})")
        return 0

    print(f"INVALID_ARTIFACT: {plan_path}")
    for err in errors:
        loc = "/".join(str(p) for p in err.path) or "<root>"
        print(f"  - at '{loc}': {err.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
