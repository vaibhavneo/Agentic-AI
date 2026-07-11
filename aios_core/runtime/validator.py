"""
Skill Runtime — dependency-free JSON-Schema subset validator.

Supports the subset the skill schemas actually use: type, required,
properties, additionalProperties, items, enum, minLength, minItems,
minimum, maximum, default (injected on validate).
"""
from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict, "array": list, "string": str,
    "integer": int, "number": (int, float), "boolean": bool,
}


def validate(data: Any, schema: dict, path: str = "$") -> list[str]:
    """Returns a list of error strings (empty = valid). Mutates data to
    inject declared defaults for absent optional object properties."""
    errors: list[str] = []
    t = schema.get("type")
    if t:
        expected = _TYPES.get(t)
        if expected and not isinstance(data, expected):
            return [f"{path}: expected {t}, got {type(data).__name__}"]
        if t == "integer" and isinstance(data, bool):
            return [f"{path}: expected integer, got boolean"]

    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: {data!r} not in enum {schema['enum']}")

    if isinstance(data, str) and len(data) < schema.get("minLength", 0):
        errors.append(f"{path}: shorter than minLength {schema['minLength']}")

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: {data} < minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: {data} > maximum {schema['maximum']}")

    if isinstance(data, list):
        if len(data) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                errors += validate(item, item_schema, f"{path}[{i}]")

    if isinstance(data, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in data:
                errors.append(f"{path}: missing required '{req}'")
        if schema.get("additionalProperties") is False:
            for k in data:
                if k not in props:
                    errors.append(f"{path}: unexpected property '{k}'")
        for k, sub in props.items():
            if k in data:
                errors += validate(data[k], sub, f"{path}.{k}")
            elif "default" in sub:
                data[k] = sub["default"]          # inject default

    return errors
