"""Focused W5-DSH-01 request-envelope regressions."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, ToolCallId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_core.domain.tools import ToolCall
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.reconstruction import (
    ReconstructionMismatchError,
    RequestReconstruction,
    conversation_digest,
    invocation_policy_digest,
    media_inputs_digest,
    model_config_digest,
    system_prompt_digest,
    tool_schema_digest,
)
from zebra_agent_worker.attempt_events import mirror_attempt_messages

NOW = datetime(2026, 8, 14, tzinfo=UTC)


class _IdentityGateway:
    provider = "test"
    model_name = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, *, tools=()):
        self.calls += 1
        return None

    def complete_stream(self, messages, *, tools=(), on_text_delta=None):
        self.calls += 1
        return None


def _messages() -> list[SessionMessage]:
    return [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content="durable system",
            created_at=NOW,
        ),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="durable user input",
            created_at=NOW,
        ),
    ]


def _tools() -> tuple[ModelToolDefinition, ...]:
    return (
        ModelToolDefinition(
            name="files.read",
            description="read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    )


def test_guard_rejects_invocation_policy_drift_before_gateway() -> None:
    messages = _messages()
    tools = _tools()
    expected = ModelInvocationPolicy(tool_choice=ModelToolChoice.REQUIRED)
    reconstruction = RequestReconstruction(
        stable_task_id="task-1",
        attempt_id="attempt-1",
        turn_id="turn-1",
        messages_rebuild=lambda: messages,
        system_prompt_digest=system_prompt_digest(messages),
        tool_schema_digest=tool_schema_digest(tools),
        media_digest=media_inputs_digest(()),
        model_config_digest=model_config_digest("test:test-model"),
        invocation_policy_digest=invocation_policy_digest(expected),
    )
    gateway = _IdentityGateway()
    step = HarnessModelStep(available_tools=tools, reconstruction=reconstruction)

    with pytest.raises(ReconstructionMismatchError, match="invocation policy"):
        step.request_completion(
            messages,
            gateway,
            allow_tools=True,
            invocation_policy=ModelInvocationPolicy(tool_choice=ModelToolChoice.AUTO),
        )
    assert gateway.calls == 0


def test_durable_tool_exchange_preserves_provider_envelope() -> None:
    session_id = SessionId(uuid4())
    internal_id = ToolCallId(uuid4())
    call = ToolCall(
        tool_call_id=internal_id,
        name="files.read",
        arguments={"path": "internal.txt"},
        created_at=NOW,
        provider_call_id="provider-call-1",
        provider_tool_name="read_file",
        provider_arguments={"file_path": "provider.txt"},
    )
    actual = (
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="reading",
            created_at=NOW,
            tool_calls=(call,),
        ),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.TOOL,
            content="contents",
            created_at=NOW,
            tool_call_id="provider-call-1",
            metadata={"tool_result_status": "succeeded"},
        ),
    )
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1, "assistant_message": "reading"},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.TOOL_CALL_PROPOSED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "tool_name": "files.read",
                "tool_call_id": str(internal_id),
                "arguments": {"path": "internal.txt"},
                "provider_call_id": "provider-call-1",
                "provider_tool_name": "read_file",
                "provider_arguments": {"file_path": "provider.txt"},
            },
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "files.read",
                "tool_call_id": str(internal_id),
                "status": "executed",
                "output": "contents",
                "metadata": {},
            },
            created_at=NOW,
        ),
    ]

    mirrored = mirror_attempt_messages(events, attempt_number=1, created_at=NOW)
    assert conversation_digest(mirrored) == conversation_digest(actual)
