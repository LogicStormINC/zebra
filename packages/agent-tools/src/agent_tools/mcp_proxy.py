from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from agent_core.domain.tools import ToolCall

from agent_tools.errors import ToolArgumentError

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class McpToolTarget:
    server_name: str
    tool_name: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "server_name",
            _normalize_required(self.server_name, "server_name"),
        )
        object.__setattr__(self, "tool_name", _normalize_required(self.tool_name, "tool_name"))


@dataclass(frozen=True)
class McpProxyRequest:
    tool_call_id: str
    target: McpToolTarget
    arguments: dict[str, JsonValue] = field(default_factory=dict)
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_call_id",
            _normalize_required(self.tool_call_id, "tool_call_id"),
        )
        object.__setattr__(self, "arguments", _normalize_json_object(self.arguments, "arguments"))
        object.__setattr__(self, "metadata", _normalize_json_object(self.metadata, "metadata"))

    def to_serializable(self) -> dict[str, JsonValue]:
        return {
            "tool_call_id": self.tool_call_id,
            "server_name": self.target.server_name,
            "tool_name": self.target.tool_name,
            "arguments": self.arguments,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class McpProxyResponse:
    output: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", self.output)
        object.__setattr__(self, "metadata", _normalize_json_object(self.metadata, "metadata"))

    def to_serializable(self) -> dict[str, JsonValue]:
        return {
            "output": self.output,
            "metadata": self.metadata,
        }


class McpProxyTransport(Protocol):
    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        raise NotImplementedError


def parse_mcp_tool_name(tool_name: str) -> McpToolTarget:
    normalized = _normalize_required(tool_name, "tool_name")
    parts = normalized.split(".")
    if len(parts) != 3 or parts[0] != "mcp":
        raise ToolArgumentError(
            "mcp tool names must use the format mcp.<server>.<tool>"
        )
    return McpToolTarget(server_name=parts[1], tool_name=parts[2])


def build_mcp_proxy_request(
    tool_call: ToolCall,
    *,
    metadata: dict[str, JsonValue] | None = None,
) -> McpProxyRequest:
    return McpProxyRequest(
        tool_call_id=str(tool_call.tool_call_id),
        target=parse_mcp_tool_name(tool_call.name),
        arguments=_normalize_json_object(tool_call.arguments, "arguments"),
        metadata=_normalize_json_object(metadata or {}, "metadata"),
    )


def _normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalize_json_object(
    value: Mapping[str, object],
    field_name: str,
) -> dict[str, JsonValue]:
    normalized: dict[str, JsonValue] = {}
    for key in sorted(value):
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        normalized[key] = _normalize_json_value(value[key], field_name)
    return normalized


def _normalize_json_value(value: object, field_name: str) -> JsonValue:
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_json_value(item, field_name) for item in value]
    if isinstance(value, dict):
        return _normalize_json_object(value, field_name)
    raise ValueError(f"{field_name} must contain only JSON-serializable values")
