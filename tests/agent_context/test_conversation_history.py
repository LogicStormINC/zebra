from datetime import UTC, datetime

from agent_context import SUMMARY_MARKER, compact_message_history, estimate_message_tokens
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall

NOW = datetime(2026, 7, 14, 11, 0, tzinfo=UTC)


def test_below_budget_history_is_returned_unchanged() -> None:
    messages = (_message(MessageRole.USER, "Inspect the inputs."),)

    result = compact_message_history(
        messages,
        user_goal="Inspect the inputs.",
        max_tokens=100,
        created_at=NOW,
    )

    assert result.compacted is False
    assert result.messages is messages
    assert result.before_tokens == result.after_tokens


def test_completed_older_exchange_is_compacted_with_latest_pair_intact() -> None:
    old_call = _call("old.txt", "call_old")
    latest_call = _call("latest.txt", "call_latest")
    messages = (
        _message(MessageRole.SYSTEM, "Stable context."),
        _message(MessageRole.USER, "Inspect the inputs."),
        _assistant("Reading old input.", old_call),
        _tool("call_old", "OLD-EVIDENCE-" * 200),
        _assistant("Reading latest input.", latest_call),
        _tool("call_latest", "LATEST-EVIDENCE"),
    )

    result = compact_message_history(
        messages,
        user_goal="Inspect the inputs.",
        max_tokens=180,
        created_at=NOW,
    )

    assert result.compacted is True
    assert result.within_budget is True
    assert result.after_tokens <= 180
    assert result.messages[0:2] == messages[0:2]
    assert any(SUMMARY_MARKER in message.content for message in result.messages)
    assert result.messages[-2].tool_calls == (latest_call,)
    assert result.messages[-1].tool_call_id == "call_latest"
    assert all(message.tool_call_id != "call_old" for message in result.messages)


def test_compacted_history_is_idempotent() -> None:
    old_call = _call("old.txt", "call_old")
    latest_call = _call("latest.txt", "call_latest")
    messages = (
        _message(MessageRole.USER, "Inspect the inputs."),
        _assistant("Reading old input.", old_call),
        _tool("call_old", "OLD-" * 300),
        _assistant("Reading latest input.", latest_call),
        _tool("call_latest", "LATEST"),
    )
    first = compact_message_history(
        messages,
        user_goal="Inspect the inputs.",
        max_tokens=160,
        created_at=NOW,
    )

    second = compact_message_history(
        first.messages,
        user_goal="Inspect the inputs.",
        max_tokens=160,
        created_at=NOW,
    )

    assert second.compacted is False
    assert second.messages == first.messages
    assert estimate_message_tokens(second.messages) == first.after_tokens


def test_unresolved_latest_call_is_never_summarized_away() -> None:
    old_call = _call("old.txt", "call_old")
    pending_call = _call("pending.txt", "call_pending")
    messages = (
        _message(MessageRole.USER, "Inspect the inputs."),
        _assistant("Reading old input.", old_call),
        _tool("call_old", "OLD-" * 300),
        _assistant("Reading pending input.", pending_call),
    )

    result = compact_message_history(
        messages,
        user_goal="Inspect the inputs.",
        max_tokens=160,
        created_at=NOW,
    )

    assert result.compacted is True
    assert result.messages[-1].tool_calls == (pending_call,)
    assert result.messages[-1].tool_calls[0].provider_call_id == "call_pending"


def _message(role: MessageRole, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=NOW,
    )


def _assistant(content: str, tool_call: ToolCall) -> SessionMessage:
    return _message(MessageRole.ASSISTANT, content).model_copy(update={"tool_calls": (tool_call,)})


def _tool(call_id: str, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.TOOL,
        content=content,
        created_at=NOW,
        tool_call_id=call_id,
    )


def _call(path: str, provider_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": path},
        created_at=NOW,
        provider_call_id=provider_id,
    )
