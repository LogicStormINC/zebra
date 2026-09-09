"""Bounded immutable MCP tool metadata; discovery does not grant execution."""

import json
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.execution_authority_support import digest
from agent_core.domain.extensions import McpConnection, OpaqueExtensionId


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate schema key")
        result[key] = value
    return result


class McpCatalogTool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: OpaqueExtensionId
    description: str = Field(default="", strict=True, max_length=8192)
    input_schema_json: str = Field(strict=True, max_length=65536)

    @field_validator("input_schema_json")
    @classmethod
    def canonical_schema(cls, value: str) -> str:
        try:
            parsed = json.loads(value, object_pairs_hook=_unique_object)
            if not isinstance(parsed, dict) or parsed.get("type") != "object":
                raise ValueError("MCP input schema must describe an object")
            canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except RecursionError:
            raise ValueError("MCP schema nesting exceeds parser limit") from None
        if len(canonical.encode()) > 65536:
            raise ValueError("MCP schema exceeds byte limit")
        return canonical


class McpToolCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connection: McpConnection
    protocol_version: OpaqueExtensionId
    tools: tuple[McpCatalogTool, ...] = Field(default=(), max_length=256)

    @field_validator("tools")
    @classmethod
    def canonical_tools(cls, value: tuple[McpCatalogTool, ...]) -> tuple[McpCatalogTool, ...]:
        if len({tool.name for tool in value}) != len(value):
            raise ValueError("duplicate MCP catalog tool")
        return tuple(sorted(value, key=lambda tool: tool.name))

    @model_validator(mode="after")
    def bounded_metadata(self) -> Self:
        if len(self.model_dump_json().encode()) > 1048576:
            raise ValueError("MCP catalog exceeds byte limit")
        return self

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))
