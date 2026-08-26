"""Pure durable-interrupt to AG-UI event mapping."""

from __future__ import annotations

from ag_ui.core import (
    AssistantMessage,
    Event,
    Interrupt,
    MessagesSnapshotEvent,
    RunFinishedEvent,
    StateSnapshotEvent,
)
from ag_ui.core import (
    RunFinishedInterruptOutcome as RunFinishedInterruptOutcome,
)
from agent_core.domain.events import EventType, SessionEvent

from agent_integrations.ag_ui.contracts import AgUiRunIdentity


def project_interrupt_event(
    event: SessionEvent,
    identity: AgUiRunIdentity,
    open_interrupts: dict[str, Interrupt],
    timestamp: int,
) -> tuple[Event, ...]:
    payload = event.payload
    clarification = event.event_type is EventType.CLARIFICATION_REQUESTED
    raw_id = _optional_text(payload, "clarification_id" if clarification else "tool_call_id")
    interrupt_id = f"{'clarification' if clarification else 'approval'}:{raw_id or event.event_id}"
    message = (
        _optional_text(payload, "question") if clarification else _optional_text(payload, "reason")
    ) or ("Clarification is required." if clarification else "Approval is required.")
    interrupt = Interrupt(
        id=interrupt_id,
        reason="clarification_required" if clarification else "approval_required",
        message=message,
        tool_call_id=raw_id,
        response_schema=payload.get("response_schema") if clarification else None,
    )
    open_interrupts[interrupt_id] = interrupt
    assistant_message = _optional_text(payload, "assistant_message") or message
    return (
        StateSnapshotEvent(
            timestamp=timestamp,
            snapshot={"session": {"status": "waiting_input"}, "openInterruptIds": [interrupt_id]},
        ),
        MessagesSnapshotEvent(
            timestamp=timestamp,
            messages=[
                AssistantMessage(id=f"interrupt-message:{interrupt_id}", content=assistant_message)
            ],
        ),
        RunFinishedEvent(
            timestamp=timestamp,
            thread_id=identity.thread_id,
            run_id=identity.run_id,
            outcome=RunFinishedInterruptOutcome(interrupts=[interrupt]),
        ),
    )


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
