from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from agent_core.domain.tools import (
    ToolCall,
    ToolExecutionLocation,
    ToolIdempotency,
    ToolReceipt,
    ToolResult,
    ToolRisk,
)

ToolHandler = Callable[[ToolCall], ToolResult]
MAX_TOOL_SCOPES = 32
MAX_TOOL_TIMEOUT_SECONDS = 900
MAX_TOOL_OUTPUT_BYTES = 4_194_304

__all__ = [
    "MAX_TOOL_OUTPUT_BYTES",
    "MAX_TOOL_SCOPES",
    "MAX_TOOL_TIMEOUT_SECONDS",
    "RegisteredTool",
    "ToolContract",
    "ToolExecutionLocation",
    "ToolHandler",
    "ToolIdempotency",
    "ToolReceipt",
    "ToolRisk",
]


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


@dataclass(frozen=True)
class RegisteredTool:
    contract: ToolContract
    handler: ToolHandler
    tags: tuple[str, ...] = field(default_factory=tuple)
