import json
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import ToolCallId


class ToolCallStatus(StrEnum):
    PROPOSED = "proposed"
    EXECUTED = "executed"
    FAILED = "failed"


class ToolExecutionLocation(StrEnum):
    ZEBRA = "zebra"
    HOST = "host"
    SANDBOX = "sandbox"


class ToolRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    ADMIN = "admin"


class ToolIdempotency(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ToolReceipt(BaseModel):
    """Versioned, non-secret execution receipt embedded in ToolResult."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(min_length=1, max_length=256)
    execution_location: ToolExecutionLocation
    scopes: tuple[str, ...] = Field(min_length=1, max_length=32)
    risk: ToolRisk
    status: str = Field(min_length=1, max_length=64)
    output_bytes: int = Field(ge=0, le=4_194_304)
    idempotency_key: str | None = Field(default=None, max_length=512)
    schema_version: str = Field(default="1", min_length=1, max_length=32)

    @field_validator("tool_name", "status", "schema_version")
    @classmethod
    def normalize_receipt_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool receipt text must not be blank")
        return normalized

    @field_validator("scopes", mode="before")
    @classmethod
    def normalize_receipt_scopes(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str | bytes) or value is None:
            raise ValueError("tool receipt scopes must be a sequence")
        if not isinstance(value, Iterable):
            raise ValueError("tool receipt scopes must be a sequence")
        normalized = tuple(str(scope).strip() for scope in value)
        if not normalized or any(not scope for scope in normalized):
            raise ValueError("tool receipt scopes must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("tool receipt scopes must not contain duplicates")
        return normalized

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be blank when set")
        return normalized

    def as_metadata(self) -> dict[str, object]:
        """Return a JSON-safe receipt without credentials or raw tool output."""

        return self.model_dump(mode="json")


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_call_id: ToolCallId
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    provider_call_id: str | None = None
    provider_tool_name: str | None = None
    provider_arguments: dict[str, Any] | None = None

    @property
    def approval_fingerprint(self) -> str:
        payload = {
            "arguments": self.arguments,
            "name": self.name,
            "provider_call_id": self.provider_call_id,
            "tool_call_id": str(self.tool_call_id),
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return sha256(encoded).hexdigest()

    @field_validator("name")
    @classmethod
    def ensure_name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("provider_call_id", "provider_tool_name")
    @classmethod
    def ensure_provider_call_id_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider_call_id must not be blank when set")
        return stripped

    @model_validator(mode="after")
    def ensure_provider_presentation_is_complete(self) -> "ToolCall":
        if (self.provider_tool_name is None) != (self.provider_arguments is None):
            raise ValueError(
                "provider_tool_name and provider_arguments must be set together"
            )
        return self

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_call_id: ToolCallId
    status: ToolCallStatus
    output: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    receipt: ToolReceipt | None = None
