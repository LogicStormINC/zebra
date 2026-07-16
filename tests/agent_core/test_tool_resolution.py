from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.tool_resolution import resolve_completion_tool_calls


def test_resolver_updates_completion_and_assistant_tool_calls_consistently() -> None:
    proposed = _call("agent.tools.call")
    completion = _completion(proposed)

    resolved = resolve_completion_tool_calls(
        completion,
        lambda calls: (
            calls[0].model_copy(
                update={
                    "name": "mcp.fixture.echo",
                    "arguments": {"value": "ok"},
                    "provider_tool_name": "agent.tools.call",
                    "provider_arguments": calls[0].arguments,
                }
            ),
        ),
    )

    assert resolved.tool_calls[0].name == "mcp.fixture.echo"
    assert resolved.assistant_message.tool_calls == resolved.tool_calls
    assert resolved.tool_calls[0].provider_tool_name == "agent.tools.call"


def test_resolver_rejects_identity_mutation() -> None:
    proposed = _call("agent.tools.call")

    with pytest.raises(ValueError, match="immutable call identity"):
        resolve_completion_tool_calls(
            _completion(proposed),
            lambda calls: (
                calls[0].model_copy(update={"provider_call_id": "different"}),
            ),
        )


def test_resolver_rejects_batch_length_mutation() -> None:
    with pytest.raises(ValueError, match="batch length"):
        resolve_completion_tool_calls(_completion(_call("agent.tools.call")), lambda _: ())


def test_tool_call_requires_complete_provider_presentation() -> None:
    with pytest.raises(ValueError, match="provider_tool_name and provider_arguments"):
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="mcp.fixture.echo",
            arguments={"value": "ok"},
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
            provider_tool_name="agent.tools.call",
        )


def _completion(tool_call: ToolCall) -> ModelCompletion:
    assistant = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.ASSISTANT,
        content="Calling tool.",
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        tool_calls=(tool_call,),
    )
    return ModelCompletion(assistant_message=assistant, tool_calls=(tool_call,))


def _call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments={"name": "mcp.fixture.echo", "arguments": {"value": "ok"}},
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        provider_call_id="call_provider",
    )
