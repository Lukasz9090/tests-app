#!/usr/bin/env python3
"""Validate the documented examples against the schemas — DEV TOOL, not runtime.

Each agent file carries one ```json example of the artifact that agent writes,
and an agent follows an example far more literally than a schema. When a schema
changes and the example does not, every agent is then instructed to produce an
artifact that will be rejected — and the first thing to notice is a live run.

This also validates `tc-project-profile.md`, which the Reviewer reads for its
quality gates. A malformed profile silently reverts to the built-in defaults, so
"it parses" is not something to find out during a review.

Usage:
    python .github/agents/tc-agent/tools/tc_check_examples.py [--repo .]

Exit codes:
    0 — every example and the profile validate
    1 — at least one does not (each violation printed)
    2 — the harness could not run (missing schema, unreadable file)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
TC = HERE.parents[1]
sys.path.insert(0, str(TC / "scripts"))

try:
    import tc_validate_plan as vp
except ImportError as exc:  # pragma: no cover - environment problem
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)

FENCE = re.compile(r"^```json\s*\n(.*?)\n```", re.S | re.M)

# Which schema the example in each file must satisfy.
EXPECTED = {
    "tc-planner.agent.md": TC / "schemas" / "tc-test-plan.schema.json",
    "tc-generator.agent.md": TC / "schemas" / "tc-generation-report.schema.json",
    "tc-reviewer.agent.md": TC / "schemas" / "tc-review.schema.json",
    "tc-project-profile.md": TC / "schemas" / "tc-project-profile.schema.json",
}


def load_schema(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".")
    parser.parse_args()

    failures = 0
    checked = 0

    for relative, schema_path in sorted(EXPECTED.items()):
        source = TC / relative
        if not source.is_file():
            print(f"CANNOT_RUN: {source} is missing", file=sys.stderr)
            return 2
        try:
            schema = load_schema(schema_path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"CANNOT_RUN: {exc}", file=sys.stderr)
            return 2

        blocks = FENCE.findall(source.read_text(encoding="utf-8"))
        if not blocks:
            print(f"  FAIL {relative}: no ```json example to check against "
                  f"{schema_path.name}")
            failures += 1
            continue

        for index, block in enumerate(blocks):
            checked += 1
            label = f"{relative}[{index}]" if len(blocks) > 1 else relative
            try:
                instance = json.loads(block)
            except json.JSONDecodeError as exc:
                print(f"  FAIL {label}: the example is not valid JSON — {exc}")
                failures += 1
                continue
            errors = vp.validate(instance, schema)
            if errors:
                print(f"  FAIL {label} against {schema_path.name}:")
                for error in errors:
                    print(f"         - {error}")
                failures += 1
            else:
                print(f"  ok   {label} against {schema_path.name}")

    print(f"\n{checked} example(s) checked, {failures} failed")
    if failures:
        print("An example an agent copies must satisfy the schema that judges the result.")
        return 1
    print("EXAMPLES_MATCH_SCHEMAS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
