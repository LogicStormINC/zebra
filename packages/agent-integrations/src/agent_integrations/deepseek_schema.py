from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeGuard

from agent_core.domain.modeling import ModelToolDefinition

_SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean"})
_SCALAR_KEYS = frozenset(
    {
        "type",
        "description",
        "title",
        "enum",
        "const",
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "pattern",
        "format",
    }
)
_OBJECT_KEYS = frozenset(
    {"type", "description", "title", "properties", "required", "additionalProperties", "$defs"}
)
_ARRAY_KEYS = frozenset({"type", "description", "title", "items", "minItems", "maxItems"})
_COMPOSITION_KEYS = frozenset({"description", "title", "anyOf", "$ref", "$defs"})


def validate_strict_tools(tools: tuple[ModelToolDefinition, ...]) -> None:
    for tool in tools:
        _validate_schema(tool.parameters, path=f"tool {tool.name}")


def _validate_schema(schema: object, *, path: str) -> None:
    if not isinstance(schema, Mapping):
        raise ValueError(f"DeepSeek strict schema {path} must be an object")
    if "$ref" in schema:
        _reject_unknown(schema, _COMPOSITION_KEYS, path=path)
        if not isinstance(schema["$ref"], str) or not schema["$ref"].startswith("#/"):
            raise ValueError(f"DeepSeek strict schema {path} has an invalid $ref")
        _validate_defs(schema.get("$defs"), path=path)
        return
    if "anyOf" in schema:
        _reject_unknown(schema, _COMPOSITION_KEYS, path=path)
        variants = schema["anyOf"]
        if not _is_sequence(variants) or not variants:
            raise ValueError(f"DeepSeek strict schema {path}.anyOf must not be empty")
        for index, variant in enumerate(variants):
            _validate_schema(variant, path=f"{path}.anyOf[{index}]")
        _validate_defs(schema.get("$defs"), path=path)
        return
    schema_type = schema.get("type")
    if schema_type == "object":
        _validate_object(schema, path=path)
    elif schema_type == "array":
        _reject_unknown(schema, _ARRAY_KEYS, path=path)
        if "items" not in schema:
            raise ValueError(f"DeepSeek strict schema {path} array requires items")
        _validate_schema(schema["items"], path=f"{path}.items")
    elif schema_type in _SCALAR_TYPES:
        _reject_unknown(schema, _SCALAR_KEYS, path=path)
    elif "enum" in schema:
        _reject_unknown(schema, _SCALAR_KEYS, path=path)
    else:
        raise ValueError(f"DeepSeek strict schema {path} has unsupported type {schema_type!r}")


def _validate_object(schema: Mapping[object, object], *, path: str) -> None:
    _reject_unknown(schema, _OBJECT_KEYS, path=path)
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, Mapping):
        raise ValueError(f"DeepSeek strict schema {path} object requires properties")
    if not _is_sequence(required) or any(not isinstance(item, str) for item in required):
        raise ValueError(f"DeepSeek strict schema {path} object requires a required list")
    property_names = set(properties)
    if set(required) != property_names:
        raise ValueError(f"DeepSeek strict schema {path} must require every property exactly once")
    if len(required) != len(set(required)):
        raise ValueError(f"DeepSeek strict schema {path} required list contains duplicates")
    if schema.get("additionalProperties") is not False:
        raise ValueError(f"DeepSeek strict schema {path} requires additionalProperties=false")
    for name, child in properties.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"DeepSeek strict schema {path} has an invalid property name")
        _validate_schema(child, path=f"{path}.{name}")
    _validate_defs(schema.get("$defs"), path=path)


def _validate_defs(value: object, *, path: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"DeepSeek strict schema {path}.$defs must be an object")
    for name, schema in value.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"DeepSeek strict schema {path} has an invalid $defs name")
        _validate_schema(schema, path=f"{path}.$defs.{name}")


def _reject_unknown(
    schema: Mapping[object, object],
    allowed: frozenset[str],
    *,
    path: str,
) -> None:
    unknown = sorted(str(key) for key in schema if key not in allowed)
    if unknown:
        raise ValueError(f"DeepSeek strict schema {path} uses unsupported keywords: {unknown}")


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
