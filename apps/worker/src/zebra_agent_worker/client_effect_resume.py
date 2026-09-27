"""Recover the client-effect wakeup from the durable event stream."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult


class ClientEffectWakeupError(ValueError):
    pass


@dataclass(frozen=True)
class ClientEffectWakeup:
    """Frozen resume state for one scheduled client effect."""

    effect_id: str
    tool_call: ToolCall
    status: str
    result_payload: dict[str, object]
    assistant_message: str
    conversation: tuple[SessionMessage, ...]
    model_calls_used: int
    tool_calls_executed: int


def recover_client_effect_wakeup(
    events: list[SessionEvent],
) -> ClientEffectWakeup | None:
    """Rebuild the wakeup when a trusted HARNESS resume carries the result."""

    scheduled: dict[str, dict[str, object]] = {}
    continuations: dict[str, dict[str, object]] = {}
    resume_payload: dict[str, object] | None = None
    for event in events:
        if event.event_type is EventType.CLIENT_EFFECT_SCHEDULED:
            effect_id = str(event.payload.get("client_effect_id", ""))
            if effect_id:
                scheduled[effect_id] = dict(event.payload)
        if event.event_type is EventType.SESSION_WAITING_FOR_CLIENT_EFFECT:
            metadata = event.payload.get("metadata")
            raw_continuations = (
                metadata.get("continuations") if isinstance(metadata, dict) else None
            )
            if isinstance(raw_continuations, dict):
                for key, value in raw_continuations.items():
                    if isinstance(key, str) and isinstance(value, dict):
                        continuations[key] = dict(value)
        if (
            event.event_type is EventType.SESSION_COMMAND_ACCEPTED
            and event.actor is EventActor.HARNESS
            and event.payload.get("kind") == "resume"
            and isinstance(event.payload.get("payload"), dict)
            and "client_effect_result" in event.payload["payload"]
        ):
            resume_payload = dict(event.payload["payload"])
    if resume_payload is None:
        return None
    raw_result_value = resume_payload.get("client_effect_result")
    raw_result = dict(raw_result_value) if isinstance(raw_result_value, dict) else {}
    effect_id = str(raw_result.get("client_effect_id", ""))
    scheduled_payload = scheduled.get(effect_id)
    if scheduled_payload is None:
        raise ClientEffectWakeupError(
            "resume references a client effect never scheduled on this stream"
        )
    continuation = continuations.get(effect_id, scheduled_payload)
    fallback_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name=str(raw_result.get("action_name") or scheduled_payload.get("tool_name")),
        arguments={},
        created_at=datetime.now(UTC),
    )
    frozen_call = str(scheduled_payload.get("tool_call_id", ""))
    conversation = _conversation(continuation.get("conversation"))
    tool_call = _frozen_tool_call(conversation, frozen_call) or _with_identity(
        fallback_call, frozen_call
    )
    return ClientEffectWakeup(
        effect_id=effect_id,
        tool_call=tool_call,
        status=str(raw_result.get("status", "failed")),
        result_payload=_as_dict(raw_result.get("result")),
        assistant_message=str(continuation.get("assistant_message") or ""),
        conversation=conversation,
        model_calls_used=_as_int(continuation.get("model_calls_used")),
        tool_calls_executed=_as_int(continuation.get("tool_calls_executed")),
    )


def client_effect_wakeup_completion(wakeup: ClientEffectWakeup) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=wakeup.assistant_message or "Waiting for the browser action.",
            created_at=wakeup.tool_call.created_at,
            tool_calls=(wakeup.tool_call,),
        ),
        tool_calls=(wakeup.tool_call,),
    )


def client_effect_wakeup_tool_result(wakeup: ClientEffectWakeup) -> ToolResult:
    executed = wakeup.status == "succeeded"
    return ToolResult(
        tool_call_id=wakeup.tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED if executed else ToolCallStatus.FAILED,
        output=json.dumps(
            {"status": wakeup.status, "result": wakeup.result_payload},
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ),
        metadata={
            "client_effect_id": wakeup.effect_id,
            "client_effect_status": wakeup.status,
            "durable_client_effect": True,
        },
    )


def _as_dict(value: Any) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _conversation(raw: Any) -> tuple[SessionMessage, ...]:
    if not isinstance(raw, list):
        return ()
    messages: list[SessionMessage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            messages.append(SessionMessage.model_validate(item))
        except ValueError:
            continue
    return tuple(messages)


def _with_identity(tool_call: ToolCall, frozen_call: str) -> ToolCall:
    """Resume restores the ORIGINAL tool call identity."""

    from uuid import UUID

    from agent_core.domain.identifiers import ToolCallId

    if not frozen_call:
        return tool_call
    return tool_call.model_copy(
        update={"tool_call_id": ToolCallId(UUID(frozen_call))}
    )


def _frozen_tool_call(
    conversation: tuple[SessionMessage, ...], frozen_call: str
) -> ToolCall | None:
    for message in reversed(conversation):
        if message.role is not MessageRole.ASSISTANT:
            continue
        for call in message.tool_calls:
            if str(call.tool_call_id) == frozen_call:
                return call
    return None
