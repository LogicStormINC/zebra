"""Provider protocol firewall.

Validates that the message list handed to a model gateway satisfies the
tool-call/tool-result pairing contract before the request leaves the harness.

The OpenAI-compatible wire format (used by DeepSeek and others) requires:

* every ``role=tool`` message carries a ``tool_call_id`` that matches the
  ``id`` of a tool_call declared in a preceding ``role=assistant`` message;
* every assistant tool_call is answered by exactly one tool result before the
  next model request (providers reject dangling tool_calls with
  ``invalid_request``);
* no duplicate tool_call identifiers collide on the wire.

A violation surfaces as :class:`HarnessInvariantError` with an actionable
message instead of a generic provider error after a wasted round-trip.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall


class HarnessInvariantError(RuntimeError):
    """Raised when the harness would hand a structurally invalid request to a provider."""


def _tool_call_wire_id(tool_call: ToolCall) -> str:
    # Mirrors the serialization key in openai_payloads.serialize_message and
    # HarnessModelStep.append_tool_result so the firewall checks exactly what
    # the provider will receive.
    return tool_call.provider_call_id or str(tool_call.tool_call_id)


def validate_tool_call_pairing(messages: Sequence[SessionMessage]) -> None:
    """Validate tool-call/tool-result pairing across the whole message list.

    Raises :class:`HarnessInvariantError` on the first structural violation.

    The last assistant tool-call batch is allowed to be unpaired only when it
    is not the final message — the harness calls this validator after every
    tool result has been appended, so a trailing assistant message with
    unanswered tool_calls indicates a harness bug.
    """
    seen_tool_call_ids: set[str] = set()
    pending_tool_calls: set[str] = set()

    for index, message in enumerate(messages):
        if message.role is MessageRole.ASSISTANT and message.tool_calls:
            for tool_call in message.tool_calls:
                wire_id = _tool_call_wire_id(tool_call)
                if wire_id in seen_tool_call_ids:
                    raise HarnessInvariantError(
                        f"duplicate tool_call id '{wire_id}' at message {index}; "
                        "provider would reject the request"
                    )
                seen_tool_call_ids.add(wire_id)
                pending_tool_calls.add(wire_id)
        elif message.role is MessageRole.TOOL:
            tool_call_id = message.tool_call_id
            if tool_call_id is None:
                # Per-message validation already forbids this, but keep the
                # firewall self-contained.
                raise HarnessInvariantError(
                    f"tool message at index {index} lacks tool_call_id"
                )
            if tool_call_id not in seen_tool_call_ids:
                raise HarnessInvariantError(
                    f"tool message at index {index} references tool_call_id "
                    f"'{tool_call_id}' with no preceding assistant tool_call; "
                    "provider would reject the orphan result"
                )
            pending_tool_calls.discard(tool_call_id)

    if pending_tool_calls:
        missing = ", ".join(sorted(pending_tool_calls))
        raise HarnessInvariantError(
            f"assistant tool_calls without matching tool results before model "
            f"request: {missing}; provider would reject the dangling calls"
        )
