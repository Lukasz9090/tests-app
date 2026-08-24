#!/usr/bin/env python3
"""Validate an agent artifact against its JSON Schema — no third-party deps.

Implements the subset of JSON Schema draft 2020-12 that the agent schemas
actually use: type, required, properties, additionalProperties, items,
minItems/maxItems, minimum/maximum/exclusive*, minLength/maxLength, pattern,
enum, const, uniqueItems, allOf/anyOf/oneOf/not, if/then/else and local $ref
($defs). Anything else in a schema is ignored rather than guessed at, so a
schema using an unsupported keyword still validates the parts it can.

Usage:
  validate_plan.py <artifact.md|artifact.json> <schema.json>

Exit 0 = artifact valid. Exit 1 = INVALID_ARTIFACT (with every violation
listed, not just the first).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

JSON_FENCE = re.compile(r"^```json\s*\n(.*?)\n```", re.S | re.M)

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def type_matches(value, expected: str) -> bool:
    if expected == "integer":
        # bool is a subclass of int in Python; JSON Schema treats them apart
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer_like":
        return False
    python_type = TYPES.get(expected)
    if python_type is None:
        return True  # unknown type name: do not invent a failure
    if python_type is dict:
        return isinstance(value, dict)
    if python_type is list:
        return isinstance(value, list)
    if python_type is str:
        return isinstance(value, str)
    return isinstance(value, python_type)


def resolve_ref(ref: str, root: dict):
    """Resolve a local pointer such as '#/$defs/scenario'."""
    if not ref.startswith("#"):
        raise ValueError(f"only local $ref is supported, got {ref!r}")
    node = root
    for token in ref.lstrip("#/").split("/"):
        if not token:
            continue
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        else:
            node = node[token]
    return node


def json_equal(left, right) -> bool:
    """Equality with JSON semantics, not Python's.

    Python evaluates True == 1, so a plain == would accept `"schema_version":
    true` for `"const": 1`. JSON Schema keeps booleans and numbers distinct.
    """
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def describe(value) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def validate(instance, schema, root=None, path="$") -> list:
    """Return a list of human-readable violations (empty list = valid)."""
    if root is None:
        root = schema
    errors = []

    if not isinstance(schema, dict):
        return errors  # `true`/`false` schemas: treat as permissive

    if "$ref" in schema:
        return validate(instance, resolve_ref(schema["$ref"], root), root, path)

    # --- type ---------------------------------------------------------------
    if "type" in schema:
        expected = schema["type"]
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(type_matches(instance, name) for name in allowed):
            errors.append(f"{path}: expected type {'/'.join(allowed)}, got {type(instance).__name__}")
            return errors  # further checks would be noise

    # --- const / enum -------------------------------------------------------
    if "const" in schema and not json_equal(instance, schema["const"]):
        errors.append(f"{path}: must be {describe(schema['const'])}, got {describe(instance)}")
    if "enum" in schema and not any(json_equal(instance, v) for v in schema["enum"]):
        allowed = ", ".join(describe(v) for v in schema["enum"])
        errors.append(f"{path}: {describe(instance)} is not one of [{allowed}]")

    # --- numbers ------------------------------------------------------------
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: {instance} <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: {instance} >= exclusiveMaximum {schema['exclusiveMaximum']}")
        if "multipleOf" in schema and schema["multipleOf"]:
            quotient = instance / schema["multipleOf"]
            if abs(quotient - round(quotient)) > 1e-9:
                errors.append(f"{path}: {instance} is not a multiple of {schema['multipleOf']}")

    # --- strings ------------------------------------------------------------
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: {describe(instance)} does not match /{schema['pattern']}/")

    # --- arrays -------------------------------------------------------------
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: has {len(instance)} items, minItems is {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: has {len(instance)} items, maxItems is {schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in instance]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items are not unique")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors += validate(item, schema["items"], root, f"{path}[{index}]")

    # --- objects ------------------------------------------------------------
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property '{key}'")
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in instance:
                errors += validate(instance[key], subschema, root, f"{path}.{key}")
        pattern_properties = schema.get("patternProperties", {})
        for pattern, subschema in pattern_properties.items():
            for key, value in instance.items():
                if re.search(pattern, key):
                    errors += validate(value, subschema, root, f"{path}.{key}")
        extra = schema.get("additionalProperties", True)
        if extra is not True:
            known = set(properties)
            unknown = [
                key
                for key in instance
                if key not in known
                and not any(re.search(p, key) for p in pattern_properties)
            ]
            if extra is False:
                for key in unknown:
                    errors.append(f"{path}: unexpected property '{key}'")
            else:
                for key in unknown:
                    errors += validate(instance[key], extra, root, f"{path}.{key}")

    # --- combinators --------------------------------------------------------
    for subschema in schema.get("allOf", []):
        errors += validate(instance, subschema, root, path)
    if "anyOf" in schema:
        if not any(not validate(instance, s, root, path) for s in schema["anyOf"]):
            errors.append(f"{path}: does not match any schema in anyOf")
    if "oneOf" in schema:
        matches = sum(1 for s in schema["oneOf"] if not validate(instance, s, root, path))
        if matches != 1:
            errors.append(f"{path}: matches {matches} schemas in oneOf, expected exactly 1")
    if "not" in schema and not validate(instance, schema["not"], root, path):
        errors.append(f"{path}: must NOT match the 'not' schema")

    # --- conditional --------------------------------------------------------
    if "if" in schema:
        branch = "then" if not validate(instance, schema["if"], root, path) else "else"
        if branch in schema:
            errors += validate(instance, schema[branch], root, path)

    return errors


def load_payload(path: Path):
    """Read the artifact: the single ```json fence of a markdown container,
    or the whole file when it is plain JSON."""
    if not path.exists():
        raise ValueError(f"file not found: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    blocks = JSON_FENCE.findall(text)
    if len(blocks) != 1:
        raise ValueError(
            f"expected exactly one ```json fence at the start of a line, found {len(blocks)}"
        )
    return json.loads(blocks[0])


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2
    artifact_path, schema_path = Path(sys.argv[1]), Path(sys.argv[2])

    try:
        instance = load_payload(artifact_path)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID_ARTIFACT {artifact_path}: {exc}")
        return 1
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID_SCHEMA {schema_path}: {exc}")
        return 2

    errors = validate(instance, schema)
    if errors:
        print(f"INVALID_ARTIFACT {artifact_path} ({len(errors)} violation(s)):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"VALID {artifact_path} against {schema_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())