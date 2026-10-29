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
from agent_core.harness.orchestration_events import continuation_metadata

from zebra_agent_worker.client_effect_continuation import blocks_client_effect_recovery
from zebra_agent_worker.continuation_boundaries import has_later_attempt_result_boundary


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
    metadata: dict[str, object] | None = None


def recover_client_effect_wakeup(
    events: list[SessionEvent],
) -> ClientEffectWakeup | None:
    """Rebuild the wakeup when a trusted HARNESS resume carries the result."""

    scheduled: dict[str, dict[str, object]] = {}
    scheduled_indexes: dict[str, int] = {}
    continuations: dict[str, dict[str, object]] = {}
    resume_payload: dict[str, object] | None = None
    resume_indexes: dict[str, int] = {}
    for index, event in enumerate(events):
        if event.event_type is EventType.CLIENT_EFFECT_SCHEDULED:
            effect_id = str(event.payload.get("client_effect_id", ""))
            if effect_id:
                scheduled[effect_id] = dict(event.payload)
                scheduled_indexes[effect_id] = index
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
            result = resume_payload.get("client_effect_result")
            if isinstance(result, dict):
                resume_indexes.setdefault(str(result.get("client_effect_id", "")), index)
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
    resume_index = resume_indexes.get(effect_id, len(events))
    if any(blocks_client_effect_recovery(event)
           for event in events[scheduled_indexes[effect_id] + 1:]):
        return None
    # Include legacy unmarked starts: uncertainty must not replay a provider call.
    starts = [
        index for index, event in enumerate(events)
        if index > resume_index and event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    later = events[resume_index + 1:]
    if not starts:
        # A fast receipt can precede its own waiting marker, not a consumption.
        later = [event for event in later if not (
            event.event_type is EventType.SESSION_WAITING_FOR_CLIENT_EFFECT
            and effect_id in event.payload.get("client_effect_ids", [])
        )]
    if has_later_attempt_result_boundary(later, after_index=-1):
        return None
    continuation = continuations.get(effect_id, scheduled_payload)
    frozen_metadata = continuation.get("continuation_metadata")
    fallback_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name=str(raw_result.get("action_name") or scheduled_payload.get("tool_name")),
        arguments={},
        created_at=datetime.now(UTC),
    )
    frozen_call = str(scheduled_payload.get("tool_call_id", ""))
    conversation, dropped_proposals = _provider_safe_conversation(
        _conversation(continuation.get("conversation")), frozen_call
    )
    tool_call = _frozen_tool_call(conversation, frozen_call) or _with_identity(
        fallback_call, frozen_call
    )
    wakeup_metadata: dict[str, object] | None = None
    if isinstance(frozen_metadata, dict):
        wakeup_metadata = continuation_metadata(frozen_metadata)
        if starts:
            wakeup_metadata["client_effect_recovery_uncertain"] = True
        if dropped_proposals:
            wakeup_metadata["client_effect_unexecuted_proposals_dropped"] = dropped_proposals
    return ClientEffectWakeup(
        effect_id=effect_id,
        tool_call=tool_call,
        status=str(raw_result.get("status", "failed")),
        result_payload=_as_dict(raw_result.get("result")),
        assistant_message=str(continuation.get("assistant_message") or ""),
        conversation=conversation,
        model_calls_used=_as_int(continuation.get("model_calls_used")),
        tool_calls_executed=_as_int(continuation.get("tool_calls_executed")),
        metadata=wakeup_metadata,
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


def _provider_safe_conversation(
    conversation: tuple[SessionMessage, ...], deferred_call: str
) -> tuple[tuple[SessionMessage, ...], list[str]]:
    """Rebase the suspended assistant batch to durably covered calls.

    A sequential mixed batch stops at the first deferred client effect, so
    later proposals never executed and hold no durable result; replaying them
    would hand the provider dangling tool calls. Keep calls answered inside
    the frozen conversation plus the deferred call itself, and report the
    dropped proposal ids. Earlier assistant batches already passed the
    pairing firewall before the suspended request and stay untouched.
    """
    answered = {
        str(message.tool_call_id)
        for message in conversation
        if message.role is MessageRole.TOOL and message.tool_call_id is not None
    }
    for index in range(len(conversation) - 1, -1, -1):
        message = conversation[index]
        if message.role is not MessageRole.ASSISTANT or not message.tool_calls:
            continue
        call_ids = [str(call.tool_call_id) for call in message.tool_calls]
        if deferred_call not in call_ids:
            return conversation, []
        covered_ids = {call_id for call_id in call_ids if call_id in answered}
        covered_ids.add(deferred_call)
        if covered_ids == set(call_ids):
            return conversation, []
        covered = tuple(
            call
            for call, call_id in zip(message.tool_calls, call_ids, strict=True)
            if call_id in covered_ids
        )
        dropped = sorted(set(call_ids) - covered_ids)
        rebased = message.model_copy(update={"tool_calls": covered})
        return (*conversation[:index], rebased, *conversation[index + 1 :]), dropped
    return conversation, []
