"""Minimal JSON Schema (draft-07 subset) validator — standard library only.

Supports exactly the keywords used by Illuminate's own schemas
(pack.schema.json / skill-contract.schema.json):

  - type, required, properties, items (single schema)
  - additionalProperties (false only), enum, const, pattern
  - $ref to internal "#/definitions/..." paths

Unknown keywords are ignored, matching draft-07 behaviour of allowing
annotations. This is intentionally a bounded subset: if a schema needs a
keyword not listed here, extend this module rather than importing a
third-party dependency.
"""

import re
from typing import Any, Dict, List, Optional


def _type_name(instance: Any) -> str:
    if instance is None:
        return "null"
    if isinstance(instance, bool):
        return "boolean"
    if isinstance(instance, int):
        return "integer"
    if isinstance(instance, float):
        return "number"
    if isinstance(instance, str):
        return "string"
    if isinstance(instance, list):
        return "array"
    if isinstance(instance, dict):
        return "object"
    return "object"


def _matches_type(instance: Any, expected: str) -> bool:
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    return _type_name(instance) == expected


def _resolve_ref(schema: Dict, ref: str, root: Dict) -> Optional[Dict]:
    """Resolve an internal "#/definitions/<name>" reference."""
    if not ref.startswith("#/definitions/"):
        return None
    name = ref[len("#/definitions/"):]
    return root.get("definitions", {}).get(name)


def _validate(instance: Any, schema: Dict, root: Dict, path: str) -> List[str]:
    errors: List[str] = []

    if "$ref" in schema:
        resolved = _resolve_ref(schema, schema["$ref"], root)
        if resolved is None:
            errors.append(f"{path}: unresolvable $ref {schema['$ref']!r}")
            return errors
        errors.extend(_validate(instance, resolved, root, path))
        # A $ref replaces the sibling keywords in draft-07.
        return errors

    if "type" in schema:
        expected = schema["type"]
        if not _matches_type(instance, expected):
            errors.append(
                f"{path}: expected type {expected!r}, got {_type_name(instance)!r}"
            )
            return errors

    if "const" in schema:
        if instance != schema["const"]:
            errors.append(
                f"{path}: expected const {schema['const']!r}, got {instance!r}"
            )
        return errors

    if "enum" in schema:
        if instance not in schema["enum"]:
            errors.append(
                f"{path}: value {instance!r} not in enum {schema['enum']!r}"
            )
        return errors

    if "pattern" in schema and isinstance(instance, str):
        if not re.search(schema["pattern"], instance):
            errors.append(
                f"{path}: string {instance!r} does not match pattern "
                f"{schema['pattern']!r}"
            )

    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for prop, prop_schema in props.items():
            if prop in instance:
                errors.extend(
                    _validate(instance[prop], prop_schema, root, f"{path}.{prop}")
                )
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: additional property {key!r} not allowed")
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property {req!r}")

    if isinstance(instance, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(
                    _validate(item, items_schema, root, f"{path}[{i}]")
                )

    return errors


def validate(instance: Any, schema: Dict) -> List[str]:
    """Validate an instance against a JSON Schema.

    Returns a list of human-readable error strings; empty means valid.
    """
    if not isinstance(schema, dict):
        return ["schema must be an object"]
    return _validate(instance, schema, schema, "$")
