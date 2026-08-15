from __future__ import annotations

import json
from collections.abc import Mapping

type ModelToolArgumentValues = tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...]

_ERROR = "business provider model_tool_argument_values are invalid"
_MAX_TOOLS = 32
_MAX_PROPERTIES = 32
_MAX_VALUES = 64
_MAX_NAME_LENGTH = 256
_MAX_VALUE_LENGTH = 512
_MAX_SERIALIZED_BYTES = 16_384


def normalize_model_tool_argument_values(
    value: object, *, require_lists: bool = False
) -> ModelToolArgumentValues:
    entries = _entries(value)
    if not entries or len(entries) > _MAX_TOOLS:
        raise ValueError(_ERROR)
    tools: list[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]] = []
    tool_names: set[str] = set()
    for tool_name, properties in entries:
        if (
            not isinstance(tool_name, str)
            or not tool_name.strip()
            or len(tool_name) > _MAX_NAME_LENGTH
            or tool_name in tool_names
        ):
            raise ValueError(_ERROR)
        tool_names.add(tool_name)
        property_entries = _entries(properties)
        if not property_entries or len(property_entries) > _MAX_PROPERTIES:
            raise ValueError(_ERROR)
        property_names: set[str] = set()
        normalized_properties: list[tuple[str, tuple[str, ...]]] = []
        for property_name, values in property_entries:
            if (
                not isinstance(property_name, str)
                or not property_name.strip()
                or len(property_name) > _MAX_NAME_LENGTH
                or property_name in property_names
                or (require_lists and not isinstance(values, list))
                or not isinstance(values, list | tuple)
                or not values
                or len(values) > _MAX_VALUES
                or not all(isinstance(item, str) and item.strip() for item in values)
                or any(len(item) > _MAX_VALUE_LENGTH for item in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError(_ERROR)
            property_names.add(property_name)
            normalized_properties.append((property_name, tuple(sorted(values))))
        if not normalized_properties:
            raise ValueError(_ERROR)
        tools.append((tool_name, tuple(sorted(normalized_properties))))
    normalized = tuple(sorted(tools))
    if len(model_tool_argument_values_json(normalized).encode()) > _MAX_SERIALIZED_BYTES:
        raise ValueError(_ERROR)
    return normalized


def validate_model_tool_argument_values(
    value: object,
    *,
    selected_tool_names: tuple[str, ...] | None,
    catalog: Mapping[str, Mapping[str, Mapping[str, object]]] | None = None,
    require_lists: bool = False,
) -> ModelToolArgumentValues:
    normalized = normalize_model_tool_argument_values(value, require_lists=require_lists)
    selected = set(selected_tool_names or ())
    if selected_tool_names is None or not {tool_name for tool_name, _ in normalized} <= selected:
        raise ValueError(_ERROR)
    if catalog is None:
        return normalized
    for tool_name, properties in normalized:
        tool_properties = catalog.get(tool_name)
        if tool_properties is None:
            raise ValueError(_ERROR)
        for property_name, _ in properties:
            schema = tool_properties.get(property_name)
            if schema is None or schema.get("type") != "string":
                raise ValueError(_ERROR)
            allowed_values = dict(properties)[property_name]
            static_enum = schema.get("enum")
            minimum = schema.get("minLength")
            maximum = schema.get("maxLength")
            if (
                static_enum is not None
                and (
                    not isinstance(static_enum, list | tuple)
                    or any(item not in static_enum for item in allowed_values)
                )
            ) or (
                isinstance(minimum, int)
                and any(len(item) < minimum for item in allowed_values)
            ) or (
                isinstance(maximum, int)
                and any(len(item) > maximum for item in allowed_values)
            ):
                raise ValueError(_ERROR)
    return normalized


def model_tool_argument_values_json(value: ModelToolArgumentValues) -> str:
    return json.dumps(
        {tool_name: {property_name: values for property_name, values in properties}
         for tool_name, properties in value},
        separators=(",", ":"),
        sort_keys=True,
    )


def model_tool_argument_values_from_json(value: str) -> ModelToolArgumentValues:
    try:
        return normalize_model_tool_argument_values(json.loads(value), require_lists=True)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(_ERROR) from exc


def model_tool_argument_values_mapping(
    value: ModelToolArgumentValues,
) -> dict[str, dict[str, tuple[str, ...]]]:
    return {
        tool_name: {property_name: values for property_name, values in properties}
        for tool_name, properties in value
    }


def _entries(value: object) -> tuple[tuple[object, object], ...]:
    if isinstance(value, Mapping):
        return tuple(value.items())
    if isinstance(value, tuple) and all(
        isinstance(entry, tuple) and len(entry) == 2 for entry in value
    ):
        return value
    raise ValueError(_ERROR)
