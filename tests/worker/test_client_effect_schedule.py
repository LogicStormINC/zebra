"""waiting_client_effect scheduling acceptance (finalization + restore)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
)
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.client_effect_continuation import (
    has_trusted_client_effect_resume,
    is_waiting_client_effect_suspension,
    restore_client_effect_wait,
)
from zebra_agent_worker.continuation_lifecycle import restore_suspended_session_claim
from zebra_agent_worker.execution_finalization import finalize_execution
from zebra_agent_worker.recovery import RecoveredSession

NOW = datetime(2026, 8, 25, tzinfo=UTC)


class _Recorder:
    def __init__(self) -> None:
        self.session = Session.create(title="t", created_at=NOW)
        self.events: list[SessionEvent] = []

    def append(self, event_type, actor, payload) -> None:
        self.events.append(
            SessionEvent.create(
                session_id=self.session.session_id,
                sequence=len(self.events),
                event_type=event_type,
                actor=actor,
                payload=payload,
                created_at=NOW,
                idempotency_key=f"test:{len(self.events)}",
            )
        )


def _attempt(outcome: HarnessAttemptOutcome, metadata: dict) -> HarnessAttemptResult:
    return HarnessAttemptResult(
        outcome=outcome,
        summary="s",
        metadata=metadata,
        emitted_events=(),
    )


def test_waiting_external_tool_suspends_as_waiting_client_effect() -> None:
    recorder = _Recorder()
    finalize_execution(
        recorder=recorder,  # type: ignore[arg-type]
        attempt_result=_attempt(
            HarnessAttemptOutcome.WAITING_EXTERNAL_TOOL,
            {
                "stop_reason": "waiting_client_effect",
                "client_effect_ids": ["e-1"],
                "assistant_message": "opening",
            },
        ),
        memory_extraction_service=None,
        memory_promotion_service=None,
        title_service=None,  # type: ignore[arg-type]
        event_store=None,  # type: ignore[arg-type]
        started_at=NOW,
    )
    waiting = [
        event
        for event in recorder.events
        if event.event_type is EventType.SESSION_WAITING_FOR_CLIENT_EFFECT
    ]
    assert len(waiting) == 1
    assert waiting[0].payload["client_effect_ids"] == ["e-1"]
    assert not [
        event
        for event in recorder.events
        if event.event_type
        in (EventType.SESSION_COMPLETED, EventType.SESSION_FAILED)
    ]


def test_restore_requires_trusted_harness_resume() -> None:
    recorder = _Recorder()
    events = [
        SessionEvent.create(
            session_id=recorder.session.session_id,
            sequence=0,
            event_type=EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            actor=EventActor.HARNESS,
            payload={"reason": "waiting_client_effect", "client_effect_ids": ["e-1"]},
            created_at=NOW,
            idempotency_key="w",
        ),
    ]
    assert is_waiting_client_effect_suspension(events)
    assert not has_trusted_client_effect_resume(events)
    assert restore_client_effect_wait(recorder, events) is False
    events.append(
        SessionEvent.create(
            session_id=recorder.session.session_id,
            sequence=1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.HARNESS,
            payload={
                "command_id": "99999999-9999-4999-8999-999999999999",
                "session_id": str(recorder.session.session_id),
                "kind": "resume",
                "expected_revision": 0,
                "idempotency_key": "resume-1",
                "payload": {
                    "client_effect_result": {
                        "client_effect_id": "e-1",
                        "status": "succeeded",
                        "result": {"opened": True},
                    }
                },
                "fingerprint": "f" * 64,
            },
            created_at=NOW,
            idempotency_key="r",
        ),
    )
    assert has_trusted_client_effect_resume(events)
    assert restore_client_effect_wait(recorder, events) is True
    assert recorder.events[-1].event_type is EventType.SESSION_RESUMED
    assert recorder.events[-1].payload["reason"] == "waiting_client_effect_resolved"


@pytest.mark.parametrize(
    ("session_status", "waiting_event_type", "waiting_payload"),
    (
        (
            SessionStatus.WAITING_CLIENT_EFFECT,
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            {"reason": "waiting_client_effect", "client_effect_ids": ["e-1"]},
        ),
        (
            SessionStatus.RUNNING,
            EventType.CLIENT_EFFECT_SCHEDULED,
            {
                "attempt_number": 1,
                "tool_name": "trench.ui.timeline.open",
                "tool_call_id": "tool-1",
                "client_effect_id": "e-1",
                "action_name": "trench.ui.timeline.open",
            },
        ),
    ),
)
def test_cloud_claim_restore_accepts_trusted_client_effect_receipt(
    session_status: SessionStatus,
    waiting_event_type: EventType,
    waiting_payload: dict[str, object],
) -> None:
    session = Session.create(title="t", created_at=NOW).model_copy(
        update={"status": session_status, "current_sequence": 1}
    )
    workspace = WorkspaceProjection(
        session_id=session.session_id,
        workspace_root="/tmp/client-effect",
        prepared_at=NOW,
        updated_at=NOW,
        current_sequence=1,
        status=WorkspaceStatus.SUSPENDED,
    )
    lease = WorkerLease(
        session_id=session.session_id,
        fence=LeaseFence(
            control_plane_epoch=UUID("11111111-1111-4111-8111-111111111111"),
            fencing_token=1,
            owner_instance_id="worker",
        ),
        checkpoint=1,
        acquired_at=NOW,
        heartbeat_at=NOW,
        expires_at=NOW.replace(hour=1),
    )
    claimed = ClaimedSession(
        recovery=RecoveredSession(session, workspace, 2, 1, False),
        lease=lease,
    )
    events = [
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=waiting_event_type,
            actor=EventActor.HARNESS,
            payload=waiting_payload,
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.HARNESS,
            payload={
                "command_id": "99999999-9999-4999-8999-999999999999",
                "session_id": str(session.session_id),
                "kind": "resume",
                "expected_revision": 0,
                "idempotency_key": "resume-claim-1",
                "payload": {"client_effect_result": {"client_effect_id": "e-1"}},
                "fingerprint": "f" * 64,
            },
            created_at=NOW,
        ),
    ]

    class Events:
        appended: list[SessionEvent] = []

        def list_for_session(self, _session_id):
            return events

        def append(self, event):
            self.appended.append(event)

    class Recovery:
        def recover_session(self, _session_id, *, worker_lease):
            assert worker_lease is lease
            return claimed.recovery

    store = Events()
    restored = restore_suspended_session_claim(
        claimed,
        cloud_deployment=True,
        control_service=None,  # type: ignore[arg-type]
        recovery_service=Recovery(),  # type: ignore[arg-type]
        started_at=NOW,
        event_store=store,  # type: ignore[arg-type]
    )

    assert restored.lease is lease
    assert store.appended[-1].event_type is EventType.SESSION_RESUMED
    assert store.appended[-1].payload["reason"] == "waiting_client_effect_resolved"
    projected = session
    for event in store.appended:
        projected = apply_event(projected, event)
    assert projected.status is SessionStatus.READY
    if session_status is SessionStatus.RUNNING:
        assert [event.event_type for event in store.appended] == [
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            EventType.SESSION_RESUMED,
        ]
        assert store.appended[0].payload["client_effect_ids"] == ["e-1"]
