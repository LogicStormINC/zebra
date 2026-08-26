"""Fenced Worker preflight: durable-close healing, then capability checks."""

from collections.abc import Callable
from datetime import datetime

from agent_core.application import current_turn, interaction_mode_of
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports import EventStorePort

from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_errors import is_sequence_race
from zebra_agent_worker.execution_events import (
    DurableHarnessEventRecorder,
    ExecutionInterrupted,
)
from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    WorkerExecutionError,
    pending_turn_close,
    reconcile_pending_turn_close,
)
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory

_REARM_CAS_RETRIES = 3


class StaleExecutionSnapshot(RuntimeError):
    """The claimed snapshot fell behind the durable stream.

    Raised when a concurrently persisted event (typically a human message
    opening the next Turn) invalidated the decision inputs between the
    claim and the preflight. The caller must re-recover the Session and
    retry once with the refreshed stream instead of executing the stale
    request (ADR-026 §5).
    """


def run_with_stale_retry[T](
    execute_once: Callable[..., T],
    *,
    recover: Callable[[], object],
    ownership_check: Callable[[], None],
) -> T:
    """Run once; on StaleExecutionSnapshot re-recover and run again.

    The recovery budget is exactly one: a second stale snapshot under
    continuous contention becomes a typed WorkerExecutionError instead
    of escaping as a bare RuntimeError.
    """
    try:
        return execute_once(None)
    except StaleExecutionSnapshot:
        ownership_check()
        try:
            return execute_once(recover())
        except StaleExecutionSnapshot as exc:
            raise WorkerExecutionError(
                "execution snapshot stayed stale after one fresh recovery"
            ) from exc


def prepare_execution_preflight(
    *,
    recorder_factory: WorkerProjectionRecorderFactory,
    claimed: ClaimedSession,
    ownership_check: Callable[[], None],
    network_profile: str,
    has_local_artifact_store: bool,
    attempt_number: int,
    started_at: datetime,
    events: list[SessionEvent] | None = None,
    event_store: EventStorePort | None = None,
) -> tuple[DurableHarnessEventRecorder, ExecutedSession | None]:
    """Build a fenced recorder, heal durable closes, then capability checks.

    ADR-026 ordering: a crashed two-phase Turn close is reconciled BEFORE
    any new attempt is persisted — a capability failure must never invert
    an already-durable Turn outcome. A conversation Segment with no open
    Turn re-parks itself in awaiting_turn instead of executing.
    """
    recorder = recorder_factory.build(
        session=claimed.recovery.session,
        workspace=claimed.recovery.workspace,
        lease=claimed.lease,
        ownership_check=ownership_check,
    )
    if events:
        pending = pending_turn_close(events)
        if pending is not None:
            try:
                return recorder, reconcile_pending_turn_close(
                    recorder=recorder, events=events, started_at=started_at
                )
            except ExecutionInterrupted:
                return recorder, _superseded_by_control_event(recorder)
            except ValueError as exc:
                # A concurrent event (e.g. cancellation) took the terminal's
                # sequence: the snapshot is stale, re-recover and retry.
                # Genuine validation failures keep their original error.
                if not is_sequence_race(exc):
                    raise
                raise StaleExecutionSnapshot(
                    "terminal reconciliation lost a sequence race"
                ) from exc
        if (
            interaction_mode_of(events) is InteractionMode.CONVERSATION
            and current_turn(events) is None
            and event_store is not None
        ):
            try:
                return recorder, _rearm_awaiting_turn(
                    recorder=recorder,
                    started_at=started_at,
                    event_store=event_store,
                )
            except ExecutionInterrupted:
                return recorder, _superseded_by_control_event(recorder)
    try:
        return recorder, reject_unsupported_setup_only(
            recorder=recorder,
            network_profile=network_profile,
            has_local_artifact_store=has_local_artifact_store,
            attempt_number=attempt_number,
            started_at=started_at,
        )
    except ExecutionInterrupted:
        return recorder, _superseded_by_control_event(recorder)


def _superseded_by_control_event(
    recorder: DurableHarnessEventRecorder,
) -> ExecutedSession:
    """A concurrent cancel/suspend took the sequence: report, don't crash.

    The recorder refreshed to the externally chosen status; the current
    execution is superseded and returns that status instead of letting
    ``ExecutionInterrupted`` escape the Worker boundary.
    """
    return ExecutedSession(
        session=recorder.session,
        events=recorder.events,
        attempt_result=HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="Superseded by a concurrent control event.",
            metadata={
                "stop_reason": "superseded_by_control_event",
                "external_status": recorder.session.status.value,
            },
        ),
    )


def _rearm_awaiting_turn(
    *,
    recorder: DurableHarnessEventRecorder,
    started_at: datetime,
    event_store: EventStorePort,
) -> ExecutedSession:
    """Park a Turn-less conversation Segment back in awaiting_turn.

    ``recorder.prepare`` refreshes the recorder from the durable stream;
    the no-open-Turn decision is re-evaluated on that refreshed canonical
    stream on every iteration. A concurrently arrived human message (or
    any other event taking the next sequence between the fresh read and
    the marker append) either raises ``StaleExecutionSnapshot`` — the
    caller re-covers and executes the new Turn — or, for Turn-neutral
    events, rebuilds the marker against the new head within a bounded
    retry; the idempotency key always binds to the refreshed head.
    """
    session_id = recorder.session.session_id
    for _ in range(_REARM_CAS_RETRIES):
        marker = recorder.prepare(
            EventType.SESSION_RESUMED,
            EventActor.HARNESS,
            {"reason": "awaiting_turn_rearm"},
            created_at=started_at,
        )
        fresh = event_store.list_for_session(session_id)
        if current_turn(fresh) is not None or pending_turn_close(fresh) is not None:
            raise StaleExecutionSnapshot(
                "a Turn appeared while re-arming; re-recover before executing"
            )
        marker = marker.model_copy(update={"idempotency_key": f"turn-rearm:{fresh[-1].event_id}"})
        try:
            recorder.append_event(marker)
        except ValueError as exc:
            # Sequence CAS conflict: a concurrent event took the slot and
            # the refresh accepted it — re-evaluate on the newer stream.
            # A same-key/different-payload conflict is NOT contention.
            if not is_sequence_race(exc):
                raise
            continue
        return ExecutedSession(
            session=recorder.session,
            events=recorder.events,
            attempt_result=HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.COMPLETED,
                summary="No open Turn to execute.",
                metadata={"stop_reason": "awaiting_turn_noop"},
            ),
        )
    raise StaleExecutionSnapshot("re-arm could not win sequence contention within its retry budget")


def reject_unsupported_setup_only(
    *,
    recorder: DurableHarnessEventRecorder,
    network_profile: str,
    has_local_artifact_store: bool,
    attempt_number: int,
    started_at: datetime,
) -> ExecutedSession | None:
    """Persist an unsupported Cloud setup-only request instead of retrying it forever."""
    if network_profile != "setup-only" or has_local_artifact_store:
        return None
    reason = "setup-only runtime requires a local Artifact payload store"
    recorder.append(
        EventType.HARNESS_ATTEMPT_STARTED,
        EventActor.HARNESS,
        {"attempt_number": attempt_number},
        created_at=started_at,
    )
    recorder.append(
        EventType.SESSION_FAILED,
        EventActor.HARNESS,
        {
            "attempt_number": attempt_number,
            "summary": reason,
            "metadata": {
                "stop_reason": "unsupported_runtime_capability",
                "network_profile": network_profile,
                "required_capability": "local_artifact_payload_store",
            },
        },
        created_at=started_at,
    )
    return ExecutedSession(
        session=recorder.session,
        events=recorder.events,
        attempt_result=HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary=reason,
            metadata={
                "stop_reason": "unsupported_runtime_capability",
                "network_profile": network_profile,
                "required_capability": "local_artifact_payload_store",
            },
        ),
    )
