"""Fail-closed Worker capability checks that must persist before harness startup."""

from collections.abc import Callable
from datetime import datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult

from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import ExecutedSession
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
) -> tuple[DurableHarnessEventRecorder, ExecutedSession | None]:
    """Build a fenced recorder, persist a terminal failure, heal a crashed close.

    ADR-026: after the capability checks, a crashed one-shot Turn close
    missing its ``SESSION_COMPLETED`` is healed idempotently here — the
    model is never re-invoked for reconciliation.
    """
    recorder = recorder_factory.build(
        session=claimed.recovery.session,
        workspace=claimed.recovery.workspace,
        lease=claimed.lease,
        ownership_check=ownership_check,
    )
    failure = reject_unsupported_setup_only(
        recorder=recorder,
        network_profile=network_profile,
        has_local_artifact_store=has_local_artifact_store,
        attempt_number=attempt_number,
        started_at=started_at,
    )
    if failure is not None:
        return recorder, failure
    if events:
        from zebra_agent_worker.execution_finalization import (  # noqa: PLC0415
            reconcile_pending_turn_close,
        )

        return recorder, reconcile_pending_turn_close(
            recorder=recorder, events=events, started_at=started_at
        )
    return recorder, None


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
