from datetime import UTC, datetime, timedelta

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.harness import HarnessEventDraft, HarnessEventRecorder, StepClock


def test_harness_event_recorder_records_and_projects_session_events() -> None:
    clock = StepClock(
        current=datetime(2026, 6, 20, 1, 30, tzinfo=UTC),
        step=timedelta(seconds=1),
    )
    recorder = HarnessEventRecorder(
        session=Session.create(title="Recorder test", created_at=clock.now()),
        clock=clock,
    )

    first = recorder.record(
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={"title": "Recorder test"},
    )
    second = recorder.record_draft(
        HarnessEventDraft(
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )

    assert first.sequence == 0
    assert second.sequence == 1
    assert first.created_at < second.created_at
    assert recorder.session.status is SessionStatus.RUNNING
    assert len(recorder.events) == 2
