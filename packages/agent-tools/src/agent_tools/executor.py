import json
from collections.abc import Mapping
from typing import Any

from agent_core.domain.tools import ToolCall, ToolResult

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError, UnknownToolError
from agent_tools.mcp_gateway import McpProxyToolGateway
from agent_tools.mcp_proxy import parse_mcp_tool_name
from agent_tools.registry import ToolRegistry

_SCHEMA_TYPES = frozenset({"array", "boolean", "integer", "number", "object", "string"})


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        mcp_proxy_gateway: McpProxyToolGateway | None = None,
    ) -> None:
        self._registry = registry
        self._mcp_proxy_gateway = mcp_proxy_gateway

    def execute(self, tool_call: ToolCall) -> ToolResult:
        try:
            registered = self._registry.get(tool_call.name)
        except UnknownToolError:
            if self._mcp_proxy_gateway is not None and _is_mcp_tool_name(tool_call.name):
                return self._mcp_proxy_gateway.execute(tool_call)
            raise
        normalized_arguments = self._normalize_arguments(tool_call, registered.contract)
        normalized_call = tool_call.model_copy(update={"arguments": normalized_arguments})
        return registered.handler(normalized_call)

    @staticmethod
    def _normalize_arguments(tool_call: ToolCall, contract: ToolContract) -> dict[str, Any]:
        missing = [
            argument
            for argument in contract.required_arguments
            if argument not in tool_call.arguments
        ]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ToolArgumentError(f"missing required arguments for {tool_call.name}: {joined}")

        properties = {
            argument: dict(contract.argument_properties.get(argument, {}))
            for argument in sorted(
                set(contract.argument_properties) | set(contract.required_arguments)
            )
        }
        normalized = _normalize_value(
            tool_call.arguments,
            {
                "type": "object",
                "properties": properties,
                "required": list(contract.required_arguments),
                "additionalProperties": False,
            },
            "arguments",
        )
        if not isinstance(normalized, dict):
            raise ToolArgumentError("invalid tool arguments at arguments: expected object")
        return normalized


def _is_mcp_tool_name(tool_name: str) -> bool:
    try:
        parse_mcp_tool_name(tool_name)
    except ToolArgumentError:
        return False
    return True


def _normalize_value(value: Any, schema: Mapping[str, object], path: str) -> Any:
    schema_type = schema.get("type")
    if schema_type in {"array", "object"} and isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            detail = ""
            items = schema.get("items")
            if (
                schema_type == "array"
                and isinstance(items, Mapping)
                and items.get("type") == "string"
            ):
                detail = " (list or tuple of strings)"
            raise ToolArgumentError(
                f"invalid JSON at {path}: expected {schema_type}{detail}"
            ) from None

    if schema_type is not None:
        if not isinstance(schema_type, str) or schema_type not in _SCHEMA_TYPES:
            raise ToolArgumentError(f"unsupported schema type at {path}")
        _validate_type(value, schema_type, path)

    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentError(f"invalid enum value at {path}")

    if schema_type == "object":
        return _normalize_object(value, schema, path)
    if schema_type == "array":
        return _normalize_array(value, schema, path)
    if schema_type == "string":
        _validate_string_bounds(value, schema, path)
    if schema_type in {"integer", "number"}:
        _validate_number_bounds(value, schema, path, schema_type)
    return value


def _validate_type(value: Any, schema_type: str, path: str) -> None:
    matches = {
        "array": isinstance(value, list | tuple),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }
    if not matches[schema_type]:
        detail = f"; requires '{path.rsplit('.', 1)[-1]}' to be a string"
        if schema_type != "string":
            detail = ""
        raise ToolArgumentError(f"invalid type at {path}: expected {schema_type}{detail}")


def _normalize_object(
    value: Any,
    schema: Mapping[str, object],
    path: str,
) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ToolArgumentError(f"invalid type at {path}: expected object")
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ToolArgumentError(f"invalid properties schema at {path}")
    required = schema.get("required", ())
    if not isinstance(required, list | tuple):
        raise ToolArgumentError(f"invalid required schema at {path}")
    for name in required:
        if name not in value:
            raise ToolArgumentError(f"missing required property at {path}: {name}")
    if schema.get("additionalProperties") is False and any(
        name not in properties for name in value
    ):
        raise ToolArgumentError(f"unsupported arguments: additionalProperties=false at {path}")

    normalized = dict(value)
    for name, property_schema in properties.items():
        if name not in value:
            continue
        if not isinstance(property_schema, Mapping):
            raise ToolArgumentError(f"invalid property schema at {path}.{name}")
        normalized[name] = _normalize_value(value[name], property_schema, f"{path}.{name}")
    return normalized


def _normalize_array(
    value: Any,
    schema: Mapping[str, object],
    path: str,
) -> list[Any]:
    if not isinstance(value, list | tuple):
        raise ToolArgumentError(f"invalid type at {path}: expected array")
    _validate_collection_bounds(value, schema, path)
    items = schema.get("items")
    if not isinstance(items, Mapping):
        return list(value)
    normalized = [
        _normalize_value(item, items, f"{path}[{index}]") for index, item in enumerate(value)
    ]
    return tuple(normalized) if isinstance(value, tuple) else normalized


def _validate_string_bounds(value: Any, schema: Mapping[str, object], path: str) -> None:
    if not isinstance(value, str):
        return
    minimum = schema.get("minLength")
    if isinstance(minimum, int) and len(value) < minimum:
        expected = "non-blank string" if minimum == 1 else "string"
        raise ToolArgumentError(f"invalid {expected} at {path}: expected length at least {minimum}")
    maximum = schema.get("maxLength")
    if isinstance(maximum, int) and len(value) > maximum:
        raise ToolArgumentError(f"invalid length at {path}: expected at most {maximum}")


def _validate_collection_bounds(value: list[Any], schema: Mapping[str, object], path: str) -> None:
    minimum = schema.get("minItems")
    if isinstance(minimum, int) and len(value) < minimum:
        raise ToolArgumentError(f"invalid item count at {path}: expected at least {minimum}")
    maximum = schema.get("maxItems")
    if isinstance(maximum, int) and len(value) > maximum:
        raise ToolArgumentError(f"invalid item count at {path}: expected at most {maximum}")


def _validate_number_bounds(
    value: Any,
    schema: Mapping[str, object],
    path: str,
    schema_type: str,
) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return
    minimum = schema.get("minimum")
    if isinstance(minimum, int | float) and value < minimum:
        raise ToolArgumentError(
            f"invalid value at {path}: expected {schema_type} at least {minimum}"
        )
    maximum = schema.get("maximum")
    if isinstance(maximum, int | float) and value > maximum:
        raise ToolArgumentError(
            f"invalid value at {path}: expected {schema_type} at most {maximum}"
        )
