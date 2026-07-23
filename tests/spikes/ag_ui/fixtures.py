from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from ag_ui.core import (
    AssistantMessage,
    Event,
    Interrupt,
    MessagesSnapshotEvent,
    ResumeEntry,
    RunAgentInput,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

THREAD_ID: Final = "task-emb-agui-01"
RUN_ID: Final = "segment-attempt-01"
RESUME_RUN_ID: Final = "segment-attempt-02"
MESSAGE_ID: Final = "message-01"
TOOL_CALL_ID: Final = "tool-call-01"
TOOL_RESULT_MESSAGE_ID: Final = "tool-result-01"
APPROVAL_INTERRUPT_ID: Final = "approval-01"
CLARIFICATION_INTERRUPT_ID: Final = "clarification-01"


def canonical_events() -> tuple[Event, ...]:
    """Return one reviewed success stream spanning every required event family."""

    return (
        RunStartedEvent(thread_id=THREAD_ID, run_id=RUN_ID),
        TextMessageStartEvent(message_id=MESSAGE_ID),
        TextMessageContentEvent(message_id=MESSAGE_ID, delta="已找到关联证据。"),
        TextMessageEndEvent(message_id=MESSAGE_ID),
        ToolCallStartEvent(
            tool_call_id=TOOL_CALL_ID,
            tool_call_name="trench.query.get_event",
            parent_message_id=MESSAGE_ID,
        ),
        ToolCallArgsEvent(tool_call_id=TOOL_CALL_ID, delta='{"eventId":"evt_123"}'),
        ToolCallEndEvent(tool_call_id=TOOL_CALL_ID),
        ToolCallResultEvent(
            message_id=TOOL_RESULT_MESSAGE_ID,
            tool_call_id=TOOL_CALL_ID,
            content=json.dumps(
                {"eventId": "evt_123", "status": "found"},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        ),
        StateSnapshotEvent(snapshot={"agent": {"status": "running"}}),
        StateDeltaEvent(delta=[{"op": "replace", "path": "/agent/status", "value": "complete"}]),
        MessagesSnapshotEvent(
            messages=[AssistantMessage(id=MESSAGE_ID, content="已找到关联证据。")]
        ),
        RunFinishedEvent(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            outcome=RunFinishedSuccessOutcome(),
        ),
    )


def open_interrupts() -> tuple[Interrupt, ...]:
    """Return two open interrupts so resume coverage cannot pass accidentally."""

    return (
        Interrupt(
            id=APPROVAL_INTERRUPT_ID,
            reason="approval_required",
            message="Save the report to Trench?",
            response_schema={
                "type": "object",
                "properties": {"approved": {"type": "boolean"}},
                "required": ["approved"],
                "additionalProperties": False,
            },
            expires_at="2026-07-24T00:00:00Z",
        ),
        Interrupt(
            id=CLARIFICATION_INTERRUPT_ID,
            reason="clarification_required",
            message="Choose the report scope.",
            response_schema={
                "type": "object",
                "properties": {"scope": {"enum": ["event", "topic"]}},
                "required": ["scope"],
                "additionalProperties": False,
            },
            expires_at="2026-07-24T00:00:00Z",
        ),
    )


def interrupted_events() -> tuple[Event, ...]:
    """Return the required snapshot-before-interrupt boundary."""

    return (
        RunStartedEvent(thread_id=THREAD_ID, run_id=RUN_ID),
        StateSnapshotEvent(
            snapshot={
                "agent": {"status": "waiting_input"},
                "openInterruptIds": [item.id for item in open_interrupts()],
            }
        ),
        MessagesSnapshotEvent(
            messages=[AssistantMessage(id=MESSAGE_ID, content="Approval is required.")]
        ),
        RunFinishedEvent(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            outcome=RunFinishedInterruptOutcome(interrupts=list(open_interrupts())),
        ),
    )


def resolved_resume_entries() -> tuple[ResumeEntry, ...]:
    """Return one response for every interrupt in ``open_interrupts``."""

    return (
        ResumeEntry(
            interrupt_id=APPROVAL_INTERRUPT_ID,
            status="resolved",
            payload={"approved": True},
        ),
        ResumeEntry(
            interrupt_id=CLARIFICATION_INTERRUPT_ID,
            status="resolved",
            payload={"scope": "event"},
        ),
    )


def resume_input(
    *,
    entries: Sequence[ResumeEntry] | None = None,
    thread_id: str = THREAD_ID,
) -> RunAgentInput:
    """Build a structurally valid follow-up input for protocol characterization."""

    selected_entries = resolved_resume_entries() if entries is None else entries
    return RunAgentInput(
        thread_id=thread_id,
        run_id=RESUME_RUN_ID,
        state={"agent": {"status": "waiting_input"}},
        messages=[AssistantMessage(id=MESSAGE_ID, content="Approval is required.")],
        tools=[],
        context=[],
        forwarded_props={},
        resume=list(selected_entries),
    )
