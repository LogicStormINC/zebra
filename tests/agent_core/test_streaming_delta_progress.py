"""Gate A red contract: tool-capable model streams emit deltas progressively.

W45-GATE-A-01: when tools are advertised, `complete_model` buffered every text
delta until the stream finished, so a browser could never render progressive
output (the long-stream, cancel, and reload E2E nodes depend on it). The
public contract is: deltas are emitted as they arrive, exactly once, in
order, and a rejected stream that already emitted public deltas must not
retry (it would duplicate public text). A rejection before any public delta
still repairs once.
"""

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.harness.model_request import complete_model
from agent_core.ports.model_gateway import ModelResponseRejectedError

CREATED_AT = datetime(2026, 8, 13, 6, 31, 12, tzinfo=UTC)

TOOLS = (
    ModelToolDefinition(
        name="files.read",
        description="Read a file.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    ),
)


def _messages() -> list[SessionMessage]:
    return [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="Stream the report.",
            created_at=CREATED_AT,
        )
    ]


def _completion(content: str) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=CREATED_AT,
        ),
        call_metadata=ModelCallMetadata(provider="openai"),
    )


class ProgressiveGateway:
    """Streams deltas and proves the sink saw them before the stream ended."""

    def __init__(self) -> None:
        self.emissions: list[str] = []
        self.progressive_after_first = False
        self.progressive_after_second = False

    def complete_stream(
        self,
        messages,
        *,
        tools=(),
        media_inputs=(),
        on_text_delta,
    ) -> ModelCompletion:
        on_text_delta(ModelTextDelta(index=0, content="Hello "))
        self.progressive_after_first = self.emissions == ["Hello "]
        on_text_delta(ModelTextDelta(index=1, content="Zebra"))
        self.progressive_after_second = self.emissions == ["Hello ", "Zebra"]
        return _completion("Hello Zebra")


def test_complete_model_emits_tool_stream_deltas_before_stream_ends() -> None:
    gateway = ProgressiveGateway()

    complete_model(
        gateway,
        _messages(),
        TOOLS,
        model_call_id="call-1",
        on_delta=lambda _call_id, delta: gateway.emissions.append(delta.content),
    )

    assert gateway.progressive_after_first is True
    assert gateway.progressive_after_second is True
    assert gateway.emissions == ["Hello ", "Zebra"]


class RejectAfterDeltaGateway:
    def __init__(self) -> None:
        self.calls = 0

    def complete_stream(
        self,
        messages,
        *,
        tools=(),
        media_inputs=(),
        on_text_delta,
    ) -> ModelCompletion:
        self.calls += 1
        on_text_delta(ModelTextDelta(index=0, content="Partial"))
        raise ModelResponseRejectedError(
            "invalid_tool_arguments_json",
            phase="tool_arguments",
            retryable=True,
            provider_tool_name="files__write",
            error_position=7,
        )


def test_rejected_stream_with_emitted_deltas_does_not_retry() -> None:
    gateway = RejectAfterDeltaGateway()
    emissions: list[str] = []

    with pytest.raises(ModelResponseRejectedError):
        complete_model(
            gateway,
            _messages(),
            TOOLS,
            model_call_id="call-1",
            on_delta=lambda _call_id, delta: emissions.append(delta.content),
        )

    assert gateway.calls == 1
    assert emissions == ["Partial"]


class RejectThenCompleteGateway:
    def __init__(self) -> None:
        self.calls = 0

    def complete_stream(
        self,
        messages,
        *,
        tools=(),
        media_inputs=(),
        on_text_delta,
    ) -> ModelCompletion:
        self.calls += 1
        if self.calls == 1:
            raise ModelResponseRejectedError(
                "invalid_tool_arguments_json",
                phase="tool_arguments",
                retryable=True,
                provider_tool_name="files__write",
                error_position=7,
            )
        on_text_delta(ModelTextDelta(index=0, content="Report ready."))
        return _completion("Report ready.")


def test_rejected_stream_without_public_deltas_still_repairs_once() -> None:
    gateway = RejectThenCompleteGateway()
    emissions: list[str] = []

    completion = complete_model(
        gateway,
        _messages(),
        TOOLS,
        model_call_id="call-1",
        on_delta=lambda _call_id, delta: emissions.append(delta.content),
    )

    assert gateway.calls == 2
    assert emissions == ["Report ready."]
    assert completion.call_metadata.response_repair_count == 1
    assert completion.call_metadata.normalized_error == "invalid_tool_arguments_json"
