#!/usr/bin/env python3
"""Validates an agent artifact against its JSON Schema (jsonschema, draft 2020-12).

A schema node may carry `errorMessage`: when anything under it fails, that sentence
replaces the generated messages.

Usage:
  tc_validate_plan.py <artifact.md|artifact.json> <schema.json>

Exit 0 = valid. Exit 1 = INVALID_ARTIFACT, every violation listed.
Exit 2 = the check could not run (missing schema, or jsonschema not installed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tc_md_payload import payload as read_payload  # noqa: E402


def _validator(schema: dict):
    """The reference validator, or a clear instruction on how to get it."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError(
            "this check needs the jsonschema library: pip install -r "
            ".github/agents/tc-agent/requirements.txt (or pip install jsonschema)"
        ) from exc
    return Draft202012Validator(schema)


def follow_ref(node, root: dict):
    """Resolve the local `$ref`s of a schema node."""
    seen = 0
    while isinstance(node, dict) and isinstance(node.get("$ref"), str) and node["$ref"].startswith("#"):
        target = root
        for part in node["$ref"].lstrip("#/").split("/"):
            if not part:
                continue
            try:
                target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                return node
        node = target
        seen += 1
        if seen > 10:                    # a cycle would otherwise spin here
            break
    return node


def custom_message(schema: dict, error) -> str | None:
    """The `errorMessage` of the deepest schema node on the failure's path, or None."""
    node = schema
    found = None
    for token in list(error.absolute_schema_path):
        node = follow_ref(node, schema)
        if isinstance(node, dict) and isinstance(node.get("errorMessage"), str):
            found = node["errorMessage"]
        try:
            node = node[int(token)] if isinstance(node, list) else node[token]
        except (KeyError, IndexError, ValueError, TypeError):
            return found
    node = follow_ref(node, schema)
    if isinstance(node, dict) and isinstance(node.get("errorMessage"), str):
        found = node["errorMessage"]
    return found


def validate(instance, schema: dict) -> list:
    """Human-readable violations of the schema; an empty list = valid."""
    violations = []
    for error in _validator(schema).iter_errors(instance):
        message = custom_message(schema, error) or error.message
        entry = f"{error.json_path}: {message}"
        if entry not in violations:      # one errorMessage covers every failure
            violations.append(entry)     # under its node, so report it once
    return sorted(violations)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2
    artifact_path, schema_path = Path(sys.argv[1]), Path(sys.argv[2])

    try:
        instance = read_payload(artifact_path)
    except (OSError, ValueError) as exc:
        print(f"INVALID_ARTIFACT {artifact_path}: {exc}")
        return 1
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID_SCHEMA {schema_path}: {exc}")
        return 2

    try:
        errors = validate(instance, schema)
    except RuntimeError as exc:
        print(f"CHECK_UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    if errors:
        print(f"INVALID_ARTIFACT {artifact_path} ({len(errors)} violation(s)):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"VALID {artifact_path} against {schema_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
