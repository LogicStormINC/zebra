"""Fenced Worker preflight: durable-close healing, then capability checks."""

from collections.abc import Callable
from datetime import datetime

from agent_core.application import current_turn, interaction_mode_of
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports import EventStorePort

from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    pending_turn_close,
    reconcile_pending_turn_close,
)
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory


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
            return recorder, reconcile_pending_turn_close(
                recorder=recorder, events=events, started_at=started_at
            )
        if (
            interaction_mode_of(events) is InteractionMode.CONVERSATION
            and current_turn(events) is None
            and event_store is not None
        ):
            rearm = _rearm_awaiting_turn(
                recorder=recorder,
                started_at=started_at,
                event_store=event_store,
            )
            if rearm is not None:
                return recorder, rearm
            # A Turn appeared on the refreshed stream: fall through and
            # execute it normally.
    return recorder, reject_unsupported_setup_only(
        recorder=recorder,
        network_profile=network_profile,
        has_local_artifact_store=has_local_artifact_store,
        attempt_number=attempt_number,
        started_at=started_at,
    )


def _rearm_awaiting_turn(
    *,
    recorder: DurableHarnessEventRecorder,
    started_at: datetime,
    event_store: EventStorePort,
) -> ExecutedSession | None:
    """Park a Turn-less conversation Segment back in awaiting_turn.

    ``recorder.prepare`` refreshes the recorder from the durable stream;
    the no-open-Turn decision is then re-evaluated on that refreshed
    canonical stream, so a human message that arrived concurrently (and
    opened a Turn) is executed instead of being parked. The idempotency
    key binds to the refreshed stream head, keeping every resume window
    distinct.
    """
    marker = recorder.prepare(
        EventType.SESSION_RESUMED,
        EventActor.HARNESS,
        {"reason": "awaiting_turn_rearm"},
        created_at=started_at,
    )
    fresh = event_store.list_for_session(recorder.session.session_id)
    if current_turn(fresh) is not None or pending_turn_close(fresh) is not None:
        return None
    marker = marker.model_copy(
        update={"idempotency_key": f"turn-rearm:{fresh[-1].event_id}"}
    )
    recorder.append_event(marker)
    return ExecutedSession(
        session=recorder.session,
        events=recorder.events,
        attempt_result=HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="No open Turn to execute.",
            metadata={"stop_reason": "awaiting_turn_noop"},
        ),
    )


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
