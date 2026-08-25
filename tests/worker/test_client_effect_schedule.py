"""waiting_client_effect scheduling acceptance (finalization + restore)."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
)
from zebra_agent_worker.client_effect_continuation import (
    has_trusted_client_effect_resume,
    is_waiting_client_effect_suspension,
    restore_client_effect_wait,
)
from zebra_agent_worker.execution_finalization import finalize_execution

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
