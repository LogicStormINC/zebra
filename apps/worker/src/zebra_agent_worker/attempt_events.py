"""Durable attempt event helpers (Wave 5 Phase 1 + Gate 1).

Stable start/outcome coordinates, usage accounting and retry decisions for
the Hosted Worker outer attempt loop. Chain validation and epoch scoping live
in ``attempt_chain``; coordination policy lives in ``attempt_coordinator``.
"""

from __future__ import annotations

from datetime import datetime

from agent_core.domain.attempt_policy import (
    ABSOLUTE_NON_RETRYABLE_STOP_REASONS,
    TaskAttemptPolicy,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
)

from zebra_agent_worker.attempt_chain import (
    AttemptReconstructionError,
    derive_epoch_coordinates,
    derive_turn_id,
    durable_usage,
    epoch_scoped_events,
    mirror_attempt_messages,
    remaining_budget,
    usage_int,
    validate_attempt_reconstruction,
)
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder

__all__ = [
    "AttemptReconstructionError",
    "attempt_for",
    "derive_epoch_coordinates",
    "derive_plan_revision",
    "derive_turn_id",
    "durable_events",
    "durable_usage",
    "epoch_scoped_events",
    "materialize_attempt_start",
    "mirror_attempt_messages",
    "reconstruct_current_attempt",
    "record_attempt_outcome",
    "remaining_budget",
    "should_retry_attempt",
    "usage_int",
    "validate_attempt_reconstruction",
]


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


def materialize_attempt_start(
    recorder: DurableHarnessEventRecorder,
    attempt: HarnessAttempt,
    session_events: list[SessionEvent],
    *,
    started_at: datetime,
    turn_id: str,
    epoch_sequence: int,
) -> bool:
    """Record the authoritative start only when missing or legacy (no stable
    identity yet), so crash recovery never duplicates a start. Returns True
    when a fresh start was recorded."""
    existing = [
        event
        for event in session_events
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
        and event.payload.get("attempt_sequence") == attempt.number
    ]
    if existing and existing[-1].payload.get("attempt_id"):
        return False
    recorder.append(
        EventType.HARNESS_ATTEMPT_STARTED,
        EventActor.HARNESS,
        {
            "attempt_number": attempt.number,
            "attempt_id": attempt.attempt_id,
            "attempt_sequence": attempt.number,
            "started_at": started_at.isoformat(),
            "causal_attempt_id": attempt.causal_attempt_id,
            "turn_id": turn_id,
            "epoch_sequence": epoch_sequence,
        },
        created_at=started_at,
    )
    return True


def record_attempt_outcome(
    recorder: DurableHarnessEventRecorder,
    *,
    attempt: HarnessAttempt,
    result: HarnessAttemptResult,
    ended_at: datetime,
    retry_scheduled: bool,
    turn_id: str,
    epoch_sequence: int,
) -> None:
    model_calls_used = usage_int(result.metadata, "model_calls_used", 1)
    tool_calls_used = usage_int(result.metadata, "tool_calls_executed", 0)
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
            "summary": result.summary,
            "turn_id": turn_id,
            "epoch_sequence": epoch_sequence,
            "result_metadata": {
                "stop_reason": str(result.metadata.get("stop_reason", "unknown")),
                "model_calls_used": model_calls_used,
                "tool_calls_executed": tool_calls_used,
            },
        },
        created_at=ended_at,
    )


def should_retry_attempt(
    policy: TaskAttemptPolicy,
    result: HarnessAttemptResult,
    attempts_used: int,
    *,
    model_calls_used: int,
    tool_calls_used: int,
    max_model_calls: int | None,
    max_tool_calls: int | None,
) -> bool:
    if result.outcome is not HarnessAttemptOutcome.FAILED:
        return False
    reason = result.metadata.get("stop_reason")
    if not isinstance(reason, str):
        return False
    if reason in ABSOLUTE_NON_RETRYABLE_STOP_REASONS:
        return False
    if reason not in policy.retryable_stop_reasons:
        return False
    # Frozen Stable Task budgets are cumulative across attempts: Attempt 2
    # must not exceed the same Task's model/tool call budget.
    if max_model_calls is not None and model_calls_used >= max_model_calls:
        return False
    if max_tool_calls is not None and tool_calls_used >= max_tool_calls:
        return False
    return attempts_used < policy.max_attempts


def derive_plan_revision(session_events: list[SessionEvent]) -> int:
    """Current durable Plan revision: 1 + count of PLAN_UPDATED facts."""
    return 1 + sum(1 for event in session_events if event.event_type is EventType.PLAN_UPDATED)


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
