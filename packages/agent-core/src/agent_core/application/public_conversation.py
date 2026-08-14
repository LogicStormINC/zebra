from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import TaskEvent

PUBLIC_CONVERSATION_SCHEMA_VERSION = "zebra.public-conversation.v1"
MAX_PUBLIC_TEXT_CHARS = 64_000
MAX_PUBLIC_CHOICE_CHARS = 256
MAX_PUBLIC_CONTEXT_CHARS = 2_000
MAX_PUBLIC_CHOICES = 20

PublicConversationRole = Literal[
    "user_message",
    "progress_summary",
    "tool_activity",
    "clarification",
    "approval",
    "final_response",
    "failure",
]
PublicConversationDisclosure = Literal["open", "collapsed"]


@dataclass(frozen=True, slots=True)
class PublicConversationItem:
    item_id: str
    cursor: int
    role: PublicConversationRole
    state: str
    default_disclosure: PublicConversationDisclosure
    created_at: str
    content: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "cursor": self.cursor,
            "role": self.role,
            "state": self.state,
            "default_disclosure": self.default_disclosure,
            "created_at": self.created_at,
            "content": self.content,
            "data": self.data,
        }


@dataclass(frozen=True, slots=True)
class PublicConversationProjection:
    schema_version: str
    task_id: str
    next_cursor: int
    items: tuple[PublicConversationItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "next_cursor": self.next_cursor,
            "items": [item.to_dict() for item in self.items],
        }


def project_public_conversation(
    task_id: TaskId,
    events: tuple[TaskEvent, ...],
    *,
    after_sequence: int = -1,
) -> PublicConversationProjection:
    if after_sequence < -1:
        raise ValueError("after_sequence must be greater than or equal to -1")
    ordered = _ordered_unique_events(events)
    final_event_ids = _public_final_event_ids(ordered)
    items: dict[str, PublicConversationItem] = {}

    for task_event in ordered:
        event = task_event.event
        event_type = event.event_type
        if event_type is EventType.USER_MESSAGE_RECEIVED:
            if event.payload.get("source") == "session_handoff":
                continue
            if event.payload.get("actor_kind") == "automation":
                continue
            content = _text(event.payload.get("public_content"))
            if content:
                _set_event_item(
                    items,
                    task_event,
                    role="user_message",
                    state="submitted",
                    disclosure="open",
                    content=content,
                )
            continue

        if event_type is EventType.MODEL_RESPONSE_RECEIVED:
            if str(event.event_id) not in final_event_ids:
                continue
            content = _text(event.payload.get("assistant_message"))
            if content:
                item_id = f"final:{event.event_id}"
                items[item_id] = _item(
                    task_event,
                    item_id=item_id,
                    role="final_response",
                    state="completed",
                    disclosure="open",
                    content=content,
                )
            continue

        if event_type in _PROGRESS_CONTENT:
            coverage_verdict = event.payload.get("coverage_verdict")
            _set_event_item(
                items,
                task_event,
                role="progress_summary",
                state=_PROGRESS_STATE[event_type],
                disclosure=_PROGRESS_DISCLOSURE[event_type],
                content=_PROGRESS_CONTENT[event_type],
                data=(
                    {"coverage_verdict": coverage_verdict}
                    if event_type is EventType.SESSION_COMPLETED
                    and isinstance(coverage_verdict, dict)
                    else None
                ),
            )
            continue

        if event_type in _TOOL_EVENTS:
            _apply_tool_event(items, task_event)
            continue

        if event_type in {
            EventType.CLARIFICATION_REQUESTED,
            EventType.CLARIFICATION_RESPONDED,
        }:
            _apply_clarification_event(items, task_event)
            continue

        if event_type in {
            EventType.APPROVAL_REQUESTED,
            EventType.APPROVAL_GRANTED,
            EventType.APPROVAL_REJECTED,
        }:
            _apply_approval_event(items, task_event)
            continue

        if event_type is EventType.SESSION_FAILED:
            public_message = (
                _text(event.payload.get("public_message"))
                or _text(event.payload.get("summary"))
                or "This task did not complete."
            )
            coverage_verdict = event.payload.get("coverage_verdict")
            _set_event_item(
                items,
                task_event,
                role="failure",
                state="failed",
                disclosure="open",
                content=public_message,
                data={
                    "retryable": bool(event.payload.get("retryable", True)),
                    **(
                        {"coverage_verdict": coverage_verdict}
                        if isinstance(coverage_verdict, dict)
                        else {}
                    ),
                },
            )

    projected = tuple(
        item
        for item in sorted(items.values(), key=lambda value: (value.cursor, value.item_id))
        if item.cursor > after_sequence
    )
    next_cursor = max((item.task_sequence for item in ordered), default=after_sequence)
    return PublicConversationProjection(
        schema_version=PUBLIC_CONVERSATION_SCHEMA_VERSION,
        task_id=str(task_id),
        next_cursor=next_cursor,
        items=projected,
    )


_PROGRESS_CONTENT = {
    EventType.MODEL_REQUEST_STARTED: "Zebra is processing the request.",
    EventType.SESSION_SUSPENDED: "The task is paused.",
    EventType.SESSION_RESUMED: "The task resumed.",
    EventType.SESSION_COMPLETED: "The task completed.",
}
_PROGRESS_STATE = {
    EventType.MODEL_REQUEST_STARTED: "active",
    EventType.SESSION_SUSPENDED: "paused",
    EventType.SESSION_RESUMED: "active",
    EventType.SESSION_COMPLETED: "completed",
}
_PROGRESS_DISCLOSURE: dict[EventType, PublicConversationDisclosure] = {
    EventType.MODEL_REQUEST_STARTED: "open",
    EventType.SESSION_SUSPENDED: "collapsed",
    EventType.SESSION_RESUMED: "open",
    EventType.SESSION_COMPLETED: "collapsed",
}
_TOOL_EVENTS = {
    EventType.TOOL_CALL_PROPOSED,
    EventType.POLICY_DECISION_MADE,
    EventType.TOOL_EXECUTION_STARTED,
    EventType.TOOL_EXECUTION_COMPLETED,
    EventType.TOOL_EXECUTION_FAILED,
}


def _ordered_unique_events(events: tuple[TaskEvent, ...]) -> tuple[TaskEvent, ...]:
    seen: set[str] = set()
    ordered: list[TaskEvent] = []
    for item in sorted(events, key=lambda value: value.task_sequence):
        event_id = str(item.event.event_id)
        if event_id in seen:
            continue
        seen.add(event_id)
        ordered.append(item)
    return tuple(ordered)


def _public_final_event_ids(events: tuple[TaskEvent, ...]) -> set[str]:
    completed_segments = {
        str(item.segment_id)
        for item in events
        if item.event.event_type is EventType.SESSION_COMPLETED
    }
    failed_segments = {
        str(item.segment_id)
        for item in events
        if item.event.event_type in {EventType.SESSION_FAILED, EventType.SESSION_CANCELLED}
    }
    terminal_attempt = {
        str(item.segment_id): item.event.payload.get("attempt_number")
        for item in events
        if item.event.event_type is EventType.SESSION_COMPLETED
    }
    accepted_attempts = {
        (
            str(item.segment_id),
            item.event.payload.get("attempt_id") or item.event.payload.get("attempt_number"),
        )
        for item in events
        if item.event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
        and item.event.payload.get("outcome") == "completed"
    }
    explicit: dict[str, TaskEvent] = {}
    legacy: dict[str, TaskEvent] = {}
    last_tool_sequence: dict[str, int] = {}
    for item in events:
        if item.event.event_type in _TOOL_EVENTS:
            last_tool_sequence[str(item.segment_id)] = item.task_sequence
    for item in events:
        event = item.event
        segment = str(item.segment_id)
        if event.event_type is not EventType.MODEL_RESPONSE_RECEIVED:
            continue
        if not _text(event.payload.get("assistant_message")):
            continue
        response_stage = event.payload.get("response_stage")
        if response_stage == "final":
            # Only the accepted attempt's candidate may become the canonical
            # final: a failed attempt's final stays attempt-private (Wave 5).
            if segment in failed_segments:
                continue
            event_attempt_id = event.payload.get("attempt_id")
            event_attempt_number = event.payload.get("attempt_number")
            if event_attempt_id is not None or event_attempt_number is not None:
                # Wave 5 candidates require an authoritative accepted attempt
                # fact; no-outcome/failed/retrying candidates remain private,
                # closing the read window before ATTEMPT_OUTCOME_RECORDED.
                if (
                    segment,
                    event_attempt_id or event_attempt_number,
                ) not in accepted_attempts:
                    continue
            terminal = terminal_attempt.get(segment)
            if (
                terminal is not None
                and event_attempt_number is not None
                and event_attempt_number != terminal
            ):
                continue
            explicit[segment] = item
            continue
        if response_stage == "tool_loop" or segment not in completed_segments:
            continue
        tool_call_count = event.payload.get("tool_call_count")
        if tool_call_count == 0 or (
            tool_call_count is None and item.task_sequence > last_tool_sequence.get(segment, -1)
        ):
            legacy[segment] = item
    return {str(item.event.event_id) for item in (*explicit.values(), *legacy.values())}


def _apply_tool_event(
    items: dict[str, PublicConversationItem],
    task_event: TaskEvent,
) -> None:
    event = task_event.event
    tool_name = _text(event.payload.get("tool_name"))
    if not tool_name:
        return
    tool_call_id = _text(event.payload.get("tool_call_id")) or str(event.event_id)
    item_id = f"tool:{task_event.segment_id}:{tool_call_id}"
    existing = items.get(item_id)
    state = "proposed"
    disclosure: PublicConversationDisclosure = "open"
    if event.event_type is EventType.POLICY_DECISION_MADE:
        decision = _text(event.payload.get("decision"))
        state = "awaiting_approval" if decision == "require_approval" else decision or "proposed"
    elif event.event_type is EventType.TOOL_EXECUTION_STARTED:
        state = "running"
    elif event.event_type is EventType.TOOL_EXECUTION_COMPLETED:
        state = "completed"
        disclosure = "collapsed"
    elif event.event_type is EventType.TOOL_EXECUTION_FAILED:
        state = "failed"
    data: dict[str, object] = {"tool_name": tool_name}
    result_status = _text(event.payload.get("status"))
    if result_status:
        data["result_status"] = result_status
    if existing is not None:
        data = {**existing.data, **data}
    items[item_id] = _item(
        task_event,
        item_id=item_id,
        role="tool_activity",
        state=state,
        disclosure=disclosure,
        content=tool_name,
        data=data,
        created_at=existing.created_at if existing is not None else None,
    )


def _apply_clarification_event(
    items: dict[str, PublicConversationItem],
    task_event: TaskEvent,
) -> None:
    event = task_event.event
    clarification_id = _text(event.payload.get("clarification_id"))
    if not clarification_id:
        return
    item_id = f"clarification:{task_event.segment_id}:{clarification_id}"
    existing = items.get(item_id)
    if event.event_type is EventType.CLARIFICATION_RESPONDED:
        if existing is None:
            return
        items[item_id] = replace(
            existing,
            cursor=task_event.task_sequence,
            state="answered",
        )
        return
    question = _text(event.payload.get("question"))
    if not question:
        return
    data: dict[str, object] = {}
    data["clarification_id"] = clarification_id
    choices = event.payload.get("choices")
    if isinstance(choices, list):
        public_choices = [
            normalized
            for choice in choices[:MAX_PUBLIC_CHOICES]
            if (normalized := _bounded_text(choice, limit=MAX_PUBLIC_CHOICE_CHARS)) is not None
        ]
        if public_choices:
            data["choices"] = public_choices
    context = _bounded_text(event.payload.get("context"), limit=MAX_PUBLIC_CONTEXT_CHARS)
    if context:
        data["context"] = context
    items[item_id] = _item(
        task_event,
        item_id=item_id,
        role="clarification",
        state="pending",
        disclosure="open",
        content=question,
        data=data,
    )


def _apply_approval_event(
    items: dict[str, PublicConversationItem],
    task_event: TaskEvent,
) -> None:
    event = task_event.event
    tool_call_id = _text(event.payload.get("tool_call_id"))
    if not tool_call_id:
        return
    item_id = f"approval:{task_event.segment_id}:{tool_call_id}"
    existing = items.get(item_id)
    if event.event_type is EventType.APPROVAL_REQUESTED:
        tool_name = _text(event.payload.get("tool_name")) or "tool action"
        approval_data: dict[str, object] = {
            "approval_id": str(task_event.segment_id),
            "tool_name": tool_name,
        }
        arguments = event.payload.get("arguments")
        if isinstance(arguments, dict):
            approval_data["argument_summary"] = {
                "argument_count": len(arguments),
                "values_redacted": True,
            }
        reason = _bounded_text(event.payload.get("reason"), limit=MAX_PUBLIC_CONTEXT_CHARS)
        if reason:
            approval_data["reason"] = reason
        items[item_id] = _item(
            task_event,
            item_id=item_id,
            role="approval",
            state="pending",
            disclosure="open",
            content=f"Approval required for {tool_name}.",
            data=approval_data,
        )
        return
    if existing is None:
        return
    state = "approved" if event.event_type is EventType.APPROVAL_GRANTED else "rejected"
    items[item_id] = replace(existing, cursor=task_event.task_sequence, state=state)


def _set_event_item(
    items: dict[str, PublicConversationItem],
    task_event: TaskEvent,
    *,
    role: PublicConversationRole,
    state: str,
    disclosure: PublicConversationDisclosure,
    content: str,
    data: dict[str, object] | None = None,
) -> None:
    item_id = f"{role}:{task_event.event.event_id}"
    items[item_id] = _item(
        task_event,
        item_id=item_id,
        role=role,
        state=state,
        disclosure=disclosure,
        content=content,
        data=data,
    )


def _item(
    task_event: TaskEvent,
    *,
    item_id: str,
    role: PublicConversationRole,
    state: str,
    disclosure: PublicConversationDisclosure,
    content: str,
    data: dict[str, object] | None = None,
    created_at: str | None = None,
) -> PublicConversationItem:
    return PublicConversationItem(
        item_id=item_id,
        cursor=task_event.task_sequence,
        role=role,
        state=state,
        default_disclosure=disclosure,
        created_at=created_at or task_event.event.created_at.isoformat(),
        content=content,
        data=data or {},
    )


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:MAX_PUBLIC_TEXT_CHARS] or None


def _bounded_text(value: object, *, limit: int) -> str | None:
    normalized = _text(value)
    if normalized is None:
        return None
    return normalized[:limit]
