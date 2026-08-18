from __future__ import annotations

import hashlib
import json

import pytest
from ag_ui.core import (
    EventType,
    Interrupt,
    ResumeEntry,
    RunAgentInput,
    RunFinishedInterruptOutcome,
)
from fixtures import (
    APPROVAL_INTERRUPT_ID,
    RESUME_RUN_ID,
    THREAD_ID,
    interrupted_events,
    resolved_resume_entries,
    resume_input,
)
from pydantic import ValidationError


def _resume_idempotency_key(run_input: RunAgentInput) -> str:
    payload = run_input.model_dump(mode="json", by_alias=True, exclude_none=True)
    normalized = {
        "threadId": payload["threadId"],
        "resume": sorted(payload["resume"], key=lambda entry: entry["interruptId"]),
    }
    encoded = json.dumps(normalized, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_interrupt_boundary_snapshots_state_and_messages_before_finish() -> None:
    events = interrupted_events()
    finished = events[-1]

    assert [event.type for event in events[-3:]] == [
        EventType.STATE_SNAPSHOT,
        EventType.MESSAGES_SNAPSHOT,
        EventType.RUN_FINISHED,
    ]
    assert isinstance(finished.outcome, RunFinishedInterruptOutcome)
    assert finished.thread_id == THREAD_ID
    assert {item.id for item in finished.outcome.interrupts} == {
        item.interrupt_id for item in resolved_resume_entries()
    }


def test_complete_resume_stays_on_thread_and_has_order_independent_identity() -> None:
    entries = resolved_resume_entries()
    forward = resume_input(entries=entries)
    reversed_order = resume_input(entries=list(reversed(entries)))

    assert forward.thread_id == THREAD_ID
    assert forward.run_id == RESUME_RUN_ID
    assert {entry.interrupt_id for entry in forward.resume or []} == {
        item.interrupt_id for item in entries
    }
    assert _resume_idempotency_key(forward) == _resume_idempotency_key(reversed_order)

    denied = resume_input(
        entries=[
            ResumeEntry(
                interrupt_id=APPROVAL_INTERRUPT_ID,
                status="resolved",
                payload={"approved": False},
            ),
            entries[1],
        ]
    )
    assert _resume_idempotency_key(forward) != _resume_idempotency_key(denied)


def test_sdk_is_structural_and_leaves_durable_validation_to_zebra() -> None:
    entries = resolved_resume_entries()
    incomplete = resume_input(entries=[entries[0]])
    wrong_thread = resume_input(thread_id="different-task")
    schema_mismatch = ResumeEntry(
        interrupt_id=APPROVAL_INTERRUPT_ID,
        status="resolved",
        payload={"approved": "yes"},
    )
    unparsed_expiry = Interrupt(
        id="approval-unparsed-expiry",
        reason="approval_required",
        response_schema={"type": "boolean"},
        expires_at="not-an-rfc3339-timestamp",
    )

    assert len(incomplete.resume or []) == 1
    assert wrong_thread.thread_id == "different-task"
    assert schema_mismatch.payload == {"approved": "yes"}
    assert unparsed_expiry.expires_at == "not-an-rfc3339-timestamp"


def test_resume_status_is_still_structurally_bounded() -> None:
    with pytest.raises(ValidationError, match="literal_error"):
        ResumeEntry.model_validate({"interruptId": APPROVAL_INTERRUPT_ID, "status": "deferred"})
