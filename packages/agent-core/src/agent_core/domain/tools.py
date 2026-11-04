import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
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
    CLIENT = "client"


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


MAX_TOOL_SCOPES = 32
MAX_TOOL_TIMEOUT_SECONDS = 900
MAX_TOOL_OUTPUT_BYTES = 4_194_304


@dataclass(frozen=True)
class ToolContract:
    name: str
    required_arguments: tuple[str, ...] = ()
    description: str = ""
    argument_properties: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    parallel_safe: bool = False
    capability_version: str = "1"
    execution_location: ToolExecutionLocation = ToolExecutionLocation.ZEBRA
    scopes: tuple[str, ...] = ()
    risk: ToolRisk = ToolRisk.READ
    timeout_seconds: int = 30
    max_output_bytes: int = 32_768
    idempotency: ToolIdempotency = ToolIdempotency.NONE
    receipt_schema_version: str = "1"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool contract name must not be blank")
        normalized_required = tuple(argument.strip() for argument in self.required_arguments)
        if any(not argument for argument in normalized_required):
            raise ValueError("required argument names must not be blank")
        object.__setattr__(self, "required_arguments", normalized_required)
        if not isinstance(self.capability_version, str) or not self.capability_version.strip():
            raise ValueError("tool contract capability_version must not be blank")
        object.__setattr__(self, "capability_version", self.capability_version.strip())
        normalized_scopes = tuple(scope.strip() for scope in self.scopes)
        if len(normalized_scopes) > MAX_TOOL_SCOPES or any(
            not scope for scope in normalized_scopes
        ):
            raise ValueError(f"tool contract scopes must contain at most {MAX_TOOL_SCOPES} values")
        if len(set(normalized_scopes)) != len(normalized_scopes):
            raise ValueError("tool contract scopes must not contain duplicates")
        if (
            self.execution_location
            in {ToolExecutionLocation.HOST, ToolExecutionLocation.CLIENT}
            and not normalized_scopes
        ):
            raise ValueError("Host and client tool contracts require at least one scope")
        object.__setattr__(self, "scopes", normalized_scopes)
        if isinstance(self.timeout_seconds, bool) or not (
            0 < self.timeout_seconds <= MAX_TOOL_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"tool contract timeout_seconds must be between 1 and {MAX_TOOL_TIMEOUT_SECONDS}"
            )
        if isinstance(self.max_output_bytes, bool) or not (
            0 < self.max_output_bytes <= MAX_TOOL_OUTPUT_BYTES
        ):
            raise ValueError(
                f"tool contract max_output_bytes must be between 1 and {MAX_TOOL_OUTPUT_BYTES}"
            )
        if (
            not isinstance(self.receipt_schema_version, str)
            or not self.receipt_schema_version.strip()
        ):
            raise ValueError("tool contract receipt_schema_version must not be blank")
        object.__setattr__(self, "receipt_schema_version", self.receipt_schema_version.strip())

    def receipt(
        self,
        *,
        status: str,
        output_bytes: int,
        idempotency_key: str | None = None,
    ) -> ToolReceipt:
        """Build a bounded receipt using this contract's authority metadata."""

        if self.idempotency is ToolIdempotency.REQUIRED and not idempotency_key:
            raise ValueError(f"tool {self.name} requires an idempotency key")
        return ToolReceipt(
            tool_name=self.name,
            execution_location=self.execution_location,
            scopes=self.scopes or ("zebra:local",),
            risk=self.risk,
            status=status,
            output_bytes=output_bytes,
            idempotency_key=idempotency_key,
            schema_version=self.receipt_schema_version,
        )
