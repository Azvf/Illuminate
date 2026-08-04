"""Minimal JSON Schema (draft-07 subset) validator — standard library only.

Supports exactly the keywords used by Illuminate's own schemas
(pack.schema.json / skill-contract.schema.json):

  - type, required, properties, items (single schema)
  - additionalProperties (false only), enum, const, pattern
  - $ref to internal "#/definitions/..." paths

Only the explicit keyword set in ``SUPPORTED_KEYWORDS`` is accepted. Any
other keyword fails closed: ``validate`` raises ``SchemaError`` listing the
unsupported keyword and its location in the schema. Unknown keywords are no
longer silently ignored. If a schema needs a keyword not listed here, extend
this module rather than importing a third-party dependency.
"""

import re
from typing import Any, Dict, List, Optional

# Keywords the subset implements for validation semantics.
_VALIDATION_KEYWORDS = {
    "type",
    "required",
    "properties",
    "items",
    "additionalProperties",
    "enum",
    "const",
    "pattern",
    "$ref",
}

# Standard annotation / container keywords that appear in Illuminate's own
# bundled schemas and are safe to carry without affecting validation.
_ANNOTATION_KEYWORDS = {
    "$schema",
    "title",
    "description",
    "default",
    "definitions",
    "$defs",
}

SUPPORTED_KEYWORDS = frozenset(_VALIDATION_KEYWORDS | _ANNOTATION_KEYWORDS)


class SchemaError(ValueError):
    """Raised when a schema uses a keyword outside the supported subset."""


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


def validate_schema_keywords(schema: Dict, path: str = "$") -> List[str]:
    """Return a list of unsupported keywords found in a schema.

    Recursively walks ``properties``/``items``/``definitions``/``$defs`` and
    follows internal ``$ref`` targets. An empty list means the schema uses
    only ``SUPPORTED_KEYWORDS``.
    """
    found: List[str] = []
    visited: set = set()

    def walk(node: Any, node_path: str) -> None:
        if not isinstance(node, dict):
            return
        marker = id(node)
        if marker in visited:
            return
        visited.add(marker)
        for key, value in node.items():
            if key not in SUPPORTED_KEYWORDS:
                found.append(f"{node_path}.{key}")
        # additionalProperties is supported only as strict `False`. The schema
        # (dict) and `True` forms are accepted by SUPPORTED_KEYWORDS but _validate
        # only honours `is False`, so any other value would be silently ignored —
        # reject it to keep fail-closed semantics.
        if "additionalProperties" in node and node["additionalProperties"] is not False:
            found.append(
                f"{node_path}.additionalProperties must be false "
                "(schema form unsupported)"
            )
        if "$ref" in node:
            resolved = _resolve_ref(node, node["$ref"], schema)
            if resolved is not None:
                walk(resolved, node_path + ".$ref")
        # name -> schema maps: keys are arbitrary names, values are schemas.
        # patternProperties is intentionally NOT treated as a schema container:
        # it is outside SUPPORTED_KEYWORDS, so the keyword loop above reports it
        # as unsupported, and its value must not be silently recursed.
        for container in ("properties", "$defs", "definitions"):
            child = node.get(container)
            if isinstance(child, dict):
                for sub_key, sub_schema in child.items():
                    walk(sub_schema, f"{node_path}.{container}.{sub_key}")
        # items supports only a single dict schema. The tuple form (a list of
        # schemas) is rejected: _validate only handles the dict form, so a list
        # would be silently skipped. Do not recurse into the list's elements.
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, node_path + ".items")
        elif isinstance(items, list):
            found.append(f"{node_path}.items tuple form unsupported")

    walk(schema, path)
    return found


def validate(instance: Any, schema: Dict) -> List[str]:
    """Validate an instance against a JSON Schema.

    Returns a list of human-readable error strings; empty means valid.

    Raises :class:`SchemaError` if the schema uses a keyword outside the
    supported subset, so unsupported structures fail closed instead of being
    silently ignored.
    """
    if not isinstance(schema, dict):
        return ["schema must be an object"]
    unsupported = validate_schema_keywords(schema)
    if unsupported:
        raise SchemaError(
            "schema uses unsupported keywords: "
            + ", ".join(unsupported)
            + f" (supported: {sorted(SUPPORTED_KEYWORDS)})"
        )
    return _validate(instance, schema, schema, "$")
