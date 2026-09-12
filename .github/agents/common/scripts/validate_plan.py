#!/usr/bin/env python3
"""Validate an agent artifact against its JSON Schema.

Thin wrapper over `jsonschema`, the reference implementation. This script used to
carry a hand-written subset of draft 2020-12 so the pipeline needed no
dependency, plus a fidelity harness to prove that subset still agreed with the
real thing — 646 lines to avoid one `pip install`. The library does the job.

One non-standard extension survives, because it is load-bearing: a schema node
may carry `errorMessage` (a string). When anything under that node fails, its
generated messages are replaced by that one sentence. `not: {pattern: ...}` is
otherwise reported as "should not be valid under the given schema", which tells
the agent that wrote the artifact nothing about what to write instead — and an
unactionable error is how a defect gets "fixed" by deleting the field.

The artifact is read through md_payload, the single fence reader shared by every
script, so a file that one tool accepts is accepted by all of them.

Usage:
  validate_plan.py <artifact.md|artifact.json> <schema.json>

Exit 0 = artifact valid. Exit 1 = INVALID_ARTIFACT, with every violation listed,
not just the first. Exit 2 = the check could not run (missing schema, or
jsonschema not installed) — never to be read as a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from md_payload import payload as read_payload  # noqa: E402


def _validator(schema: dict):
    """The reference validator, or a clear instruction on how to get it."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError(
            "this check needs the jsonschema library: pip install -r "
            ".github/agents/requirements.txt (or pip install jsonschema)"
        ) from exc
    return Draft202012Validator(schema)


def follow_ref(node, root: dict):
    """Step through a local `$ref` so the walk below does not stop at one."""
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
    """The `errorMessage` of the deepest node that owns the failure.

    A violation often surfaces far below the node that explains it: the rule
    lives on an `allOf/N/then`, while the error is raised by the `required` of an
    `items` three levels down. `absolute_schema_path` is the route from the root
    to the failing keyword, so walking it and keeping the last `errorMessage` on
    the way finds the sentence a human wrote for exactly this case.

    The route runs THROUGH `$ref`s — `items: {$ref: #/$defs/scenario}` is one
    step in the path, not a stop — so each node is resolved before indexing.
    Without that, every rule inside `$defs` silently loses its message and the
    agent gets "should not be valid under the given schema" instead.
    """
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
    """Human-readable violations, empty list = valid.

    Kept as a function because check_examples.py validates in-process.
    """
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
