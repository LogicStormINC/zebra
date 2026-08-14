"""Durable attempt event helpers (Wave 5 Phase 1).

Stable start/outcome coordinates and reconstruction rules for the Hosted
Worker outer attempt loop. These helpers only read/write durable events;
coordination policy lives in ``attempt_coordinator``.
"""

from __future__ import annotations

from datetime import datetime

from agent_core.domain.attempt_policy import TaskAttemptPolicy
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
)

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


class AttemptReconstructionError(ValueError):
    """The durable attempt stream cannot be reconstructed safely."""


def reconstruct_current_attempt(
    session_events: list[SessionEvent],
    policy: TaskAttemptPolicy,
) -> int:
    """Derive the current attempt sequence from the durable stream."""
    starts = _start_events(session_events)
    outcomes = _outcome_events(session_events)
    last_outcome = outcomes[-1] if outcomes else None
    last_start = starts[-1] if starts else None
    if last_outcome is not None:
        sequence = int(last_outcome.payload["attempt_sequence"])
        if last_outcome.payload.get("retry_scheduled"):
            if sequence >= policy.max_attempts:
                return 0
            if last_start is not None and _start_sequence(last_start) > sequence + 1:
                raise AttemptReconstructionError("attempt sequence gap detected")
            return sequence + 1
        return 0
    if last_start is not None:
        sequence = _start_sequence(last_start)
        if sequence != 1:
            raise AttemptReconstructionError("attempt started without a prior outcome")
        return 1
    return 1


def validate_attempt_reconstruction(
    session_events: list[SessionEvent],
    attempt: HarnessAttempt,
) -> None:
    """Causal-chain validation: attempt N requires a retriable outcome N-1."""
    if attempt.number == 1:
        return
    previous = next(
        (
            event
            for event in _outcome_events(session_events)
            if int(event.payload["attempt_sequence"]) == attempt.number - 1
        ),
        None,
    )
    if previous is None or not previous.payload.get("retry_scheduled"):
        raise AttemptReconstructionError(f"attempt {attempt.number} has no retriable prior outcome")


def materialize_attempt_start(
    recorder: DurableHarnessEventRecorder,
    attempt: HarnessAttempt,
    session_events: list[SessionEvent],
    *,
    started_at: datetime,
) -> None:
    """Record the authoritative start only when missing or legacy (no stable
    identity yet), so crash recovery never duplicates a start."""
    existing = [
        event
        for event in session_events
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
        and event.payload.get("attempt_sequence") == attempt.number
    ]
    if existing and existing[-1].payload.get("attempt_id"):
        return
    recorder.append(
        EventType.HARNESS_ATTEMPT_STARTED,
        EventActor.HARNESS,
        {
            "attempt_number": attempt.number,
            "attempt_id": attempt.attempt_id,
            "attempt_sequence": attempt.number,
            "started_at": started_at.isoformat(),
            "causal_attempt_id": attempt.causal_attempt_id,
        },
        created_at=started_at,
    )


def record_attempt_outcome(
    recorder: DurableHarnessEventRecorder,
    *,
    attempt: HarnessAttempt,
    result: HarnessAttemptResult,
    ended_at: datetime,
    retry_scheduled: bool,
) -> None:
    recorder.append(
        EventType.ATTEMPT_OUTCOME_RECORDED,
        EventActor.HARNESS,
        {
            "attempt_id": attempt.attempt_id,
            "attempt_sequence": attempt.number,
            "outcome": result.outcome.value,
            "ended_at": ended_at.isoformat(),
            "terminal_reason": str(result.metadata.get("stop_reason", "unknown")),
            "retry_scheduled": retry_scheduled,
            "next_attempt_sequence": attempt.number + 1 if retry_scheduled else None,
        },
        created_at=ended_at,
    )


def should_retry_attempt(
    policy: TaskAttemptPolicy,
    result: HarnessAttemptResult,
    attempts_used: int,
) -> bool:
    if result.outcome is not HarnessAttemptOutcome.FAILED:
        return False
    reason = result.metadata.get("stop_reason")
    if not isinstance(reason, str) or reason not in policy.retryable_stop_reasons:
        return False
    return attempts_used < policy.max_attempts


def attempt_for(number: int, *, started_at: datetime) -> HarnessAttempt:
    return HarnessAttempt(number=number, started_at=started_at)


def durable_events(
    session_events: list[SessionEvent],
    recorder: DurableHarnessEventRecorder,
) -> list[SessionEvent]:
    return [*session_events, *recorder.events]


def _start_events(session_events: list[SessionEvent]) -> list[SessionEvent]:
    return [
        event for event in session_events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]


def _outcome_events(session_events: list[SessionEvent]) -> list[SessionEvent]:
    return [
        event for event in session_events if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
    ]


def _start_sequence(event: SessionEvent) -> int:
    value = event.payload.get("attempt_sequence") or event.payload.get("attempt_number")
    if value is None:
        raise AttemptReconstructionError("attempt start event lacks a sequence")
    return int(value)
