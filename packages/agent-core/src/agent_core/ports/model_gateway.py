from collections.abc import Callable
from typing import Protocol, runtime_checkable

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelTextDelta,
    ModelToolDefinition,
)


class ModelResponseRejectedError(RuntimeError):
    """A provider response that Zebra must not accept or execute."""

    def __init__(
        self,
        reason: str,
        *,
        phase: str,
        retryable: bool,
        provider_tool_name: str | None = None,
        provider_call_id: str | None = None,
        error_position: int | None = None,
        payload_size: int | None = None,
        payload_sha256: str | None = None,
        response_repair_count: int = 0,
        initial_reason: str | None = None,
    ) -> None:
        if not reason.strip() or not phase.strip():
            raise ValueError("model response rejection reason and phase must not be blank")
        if response_repair_count < 0:
            raise ValueError("response_repair_count must not be negative")
        details = [reason, f"phase={phase}"]
        if provider_tool_name is not None:
            details.append(f"tool={provider_tool_name}")
        if error_position is not None:
            details.append(f"position={error_position}")
        super().__init__("model response rejected: " + ", ".join(details))
        self.reason = reason
        self.phase = phase
        self.retryable = retryable
        self.provider_tool_name = provider_tool_name
        self.provider_call_id = provider_call_id
        self.error_position = error_position
        self.payload_size = payload_size
        self.payload_sha256 = payload_sha256
        self.response_repair_count = response_repair_count
        self.initial_reason = initial_reason

    def after_repairs(
        self,
        count: int,
        *,
        initial_reason: str,
    ) -> "ModelResponseRejectedError":
        return ModelResponseRejectedError(
            self.reason,
            phase=self.phase,
            retryable=self.retryable,
            provider_tool_name=self.provider_tool_name,
            provider_call_id=self.provider_call_id,
            error_position=self.error_position,
            payload_size=self.payload_size,
            payload_sha256=self.payload_sha256,
            response_repair_count=count,
            initial_reason=initial_reason,
        )

    def metadata(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "normalized_error": self.reason,
                "response_validation_phase": self.phase,
                "provider_tool_name": self.provider_tool_name,
                "provider_call_id": self.provider_call_id,
                "error_position": self.error_position,
                "rejected_payload_bytes": self.payload_size,
                "rejected_payload_sha256": self.payload_sha256,
                "retryable": self.retryable,
                "response_repair_count": self.response_repair_count,
                "initial_rejection_reason": self.initial_reason,
            }.items()
            if value is not None
        }


@runtime_checkable
class ModelContextWindowPort(Protocol):
    @property
    def context_window(self) -> ModelContextWindow: ...


@runtime_checkable
class ModelTokenCounterPort(Protocol):
    def count_input_tokens(
        self,
        messages: tuple[SessionMessage, ...],
        tools: tuple[ModelToolDefinition, ...],
    ) -> int: ...


class ModelGatewayPort(Protocol):
    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion: ...


@runtime_checkable
class StreamingModelGatewayPort(Protocol):
    def complete_stream(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        on_text_delta: Callable[[ModelTextDelta], None],
    ) -> ModelCompletion: ...
