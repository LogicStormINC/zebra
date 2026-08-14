"""Terminal synthesis for crash/fail-closed recovery (Wave 5 Phase 1)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from agent_core.domain.events import EventType, SessionEvent
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
)
from agent_tools import EffectGuardedToolGateway

from zebra_agent_worker.attempt_events import (
    attempt_for,
    durable_events,
    materialize_attempt_start,
    record_attempt_outcome,
)
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.runtime_authority import runtime_cleanup_failure_result


def complete_terminal_after_outcome(
    *,
    recorder: DurableHarnessEventRecorder,
    scoped_events: list[SessionEvent],
    started_at: datetime,
    claimed: ClaimedSession,
    tool_gateway: EffectGuardedToolGateway,
    close_gateway: Callable[[EffectGuardedToolGateway], Exception | None],
) -> tuple[HarnessAttemptResult, HarnessAttempt]:
    """Crash between a durable outcome and the Task terminal: reconstruct the
    stored outcome faithfully and re-commit the terminal once."""
    outcomes = [
        event for event in scoped_events if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
    ]
    last = outcomes[-1]
    attempt = attempt_for(int(last.payload["attempt_sequence"]), started_at=started_at)
    cleanup_error = close_gateway(tool_gateway)
    if last.payload.get("outcome") == "completed":
        attempt_result = HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary=str(last.payload.get("summary") or "accepted"),
            metadata=_safe_metadata(last.payload),
        )
        if cleanup_error is not None:
            attempt_result = runtime_cleanup_failure_result(cleanup_error, attempt_result)
    else:
        attempt_result = HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary=str(last.payload.get("summary") or "attempt policy terminal"),
            metadata={
                "stop_reason": last.payload["terminal_reason"],
                **(_safe_metadata(last.payload)),
            },
        )
    return attempt_result, attempt


def fail_closed(
    *,
    recorder: DurableHarnessEventRecorder,
    scoped_events: list[SessionEvent],
    started_at: datetime,
    error: str,
    tool_gateway: EffectGuardedToolGateway,
    close_gateway: Callable[[EffectGuardedToolGateway], Exception | None],
    turn_id: str,
    epoch_sequence: int,
) -> tuple[HarnessAttemptResult, HarnessAttempt]:
    """Inconsistent durable reconstruction: close the gateway first, then
    record the attempt outcome and terminalize without any dispatch."""
    starts = [
        event for event in scoped_events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    sequence = (
        int(starts[-1].payload.get("attempt_sequence") or starts[-1].payload["attempt_number"])
        if starts
        else 1
    )
    attempt = attempt_for(sequence, started_at=started_at)
    durable = durable_events(scoped_events, recorder)
    materialize_attempt_start(
        recorder,
        attempt,
        durable,
        started_at=started_at,
        turn_id=turn_id,
        epoch_sequence=epoch_sequence,
    )
    cleanup_error = close_gateway(tool_gateway)
    attempt_result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="attempt reconstruction failed closed",
        metadata={
            "stop_reason": "attempt_reconstruction_invalid",
            "error_message": error,
        },
    )
    if cleanup_error is not None:
        attempt_result = runtime_cleanup_failure_result(cleanup_error, attempt_result)
    existing_outcome = any(
        event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
        and event.payload.get("attempt_sequence") == attempt.number
        for event in scoped_events
    )
    if not existing_outcome:
        record_attempt_outcome(
            recorder,
            attempt=attempt,
            result=attempt_result,
            ended_at=datetime.now(UTC),
            retry_scheduled=False,
            turn_id=turn_id,
            epoch_sequence=epoch_sequence,
        )
    return attempt_result, attempt


def _safe_metadata(payload: dict[str, object]) -> dict[str, object]:
    raw = payload.get("result_metadata")
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "stop_reason",
        "model_calls_used",
        "tool_calls_executed",
        "completion_evidence_satisfied",
        "completion_evidence_missing",
        "completion_evidence_fingerprint",
        "completion_evidence_required_count",
        "completion_evidence_satisfied_count",
        "completion_evidence_missing_count",
    }
    return {key: value for key, value in raw.items() if key in allowed}


def _budget_blocked_result(
    attempt: HarnessAttempt,
    model_calls_used: int,
    tool_calls_used: int,
    max_model_calls: int | None,
    max_tool_calls: int | None,
) -> HarnessAttemptResult | None:
    if max_model_calls is not None and model_calls_used >= max_model_calls:
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="model call budget exhausted before the attempt could dispatch",
            metadata={
                "stop_reason": "model_call_budget_exhausted",
                "model_calls_used": model_calls_used,
                "tool_calls_executed": tool_calls_used,
            },
        )
    if max_tool_calls is not None and tool_calls_used >= max_tool_calls:
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="tool call budget exhausted before the attempt could dispatch",
            metadata={
                "stop_reason": "tool_call_budget_exhausted",
                "model_calls_used": model_calls_used,
                "tool_calls_executed": tool_calls_used,
            },
        )
    return None
