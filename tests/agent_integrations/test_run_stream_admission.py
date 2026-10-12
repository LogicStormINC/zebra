from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.stream_admission import RunStreamAdmission, StreamMode
from agent_integrations.run_stream_admission import load_run_stream_admission

from tests.agent_core.test_stream_command_admission import capabilities, command


def source(*, legacy=False):
    intent = command()
    task = TaskId(uuid4())
    intent = intent.model_copy(update={"payload": {**intent.payload, "thread_id": str(task)}})
    admission = RunStreamAdmission(
        task_id=task, run_id="run-1", capabilities=capabilities(), mode=StreamMode.TRANSIENT_V2
    )
    event = SessionEvent.create(
        session_id=intent.session_id,
        sequence=4,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=intent.event_payload(stream_admission=None if legacy else admission),
        idempotency_key=intent.idempotency_key,
    )
    tasks = Mock()
    tasks.read_run_header.return_value = SimpleNamespace(
        anchor=SimpleNamespace(
            task_sequence=7,
            segment_id=event.session_id,
            event_id=event.event_id,
            segment_sequence=4,
            internal_continuation=False,
        ),
        legacy=False,
    )
    tasks.read_event_page.return_value = SimpleNamespace(
        events=(SimpleNamespace(task_sequence=7, segment_id=event.session_id, event=event),),
        has_more=False,
    )
    return tasks, task, admission


def test_indexed_single_row_and_absent_legacy_metadata():
    tasks, task, admission = source()
    assert load_run_stream_admission(tasks, task, "run-1") == admission
    tasks.read_event_page.assert_called_once_with(
        task, 6, through_sequence=7, limit=1, max_bytes=1_048_576
    )
    tasks, task, _ = source(legacy=True)
    assert load_run_stream_admission(tasks, task, "run-1") is None
    tasks.read_run_header.return_value = SimpleNamespace(anchor=None, legacy=True)
    assert load_run_stream_admission(tasks, task, "r" * 256) is None


@pytest.mark.parametrize("fault", ["gap", "wrong_event", "bad_fingerprint", "bad_metadata", "io"])
def test_unknown_or_corrupt_source_never_becomes_legacy(fault):
    tasks, task, _ = source()
    entry = tasks.read_event_page.return_value.events[0]
    if fault == "gap":
        tasks.read_event_page.return_value.has_more = True
    elif fault == "wrong_event":
        entry.task_sequence = 8
    elif fault == "bad_fingerprint":
        entry.event.payload["fingerprint"] = "0" * 64
    elif fault == "bad_metadata":
        entry.event.payload["stream_admission"]["task_id"] = str(uuid4())
    else:
        tasks.read_run_header.side_effect = TimeoutError("source timed out")
    with pytest.raises((ValueError, TimeoutError)):
        load_run_stream_admission(tasks, task, "run-1")


def test_internal_legacy_remains_legacy_but_internal_v2_is_rejected():
    tasks, task, _ = source(legacy=True)
    entry = tasks.read_event_page.return_value.events[0]
    entry.event = entry.event.model_copy(update={"actor": EventActor.HARNESS})
    assert load_run_stream_admission(tasks, task, "run-1") is None
    tasks, task, _ = source()
    entry = tasks.read_event_page.return_value.events[0]
    entry.event = entry.event.model_copy(update={"actor": EventActor.HARNESS})
    with pytest.raises(ValueError):
        load_run_stream_admission(tasks, task, "run-1")


def test_existing_typed_legacy_metadata_remains_readable():
    tasks, task, _ = source()
    entry = tasks.read_event_page.return_value.events[0]
    entry.event.payload["stream_admission"]["mode"] = "legacy"
    entry.event = entry.event.model_copy(update={"actor": EventActor.HARNESS})
    assert load_run_stream_admission(tasks, task, "run-1").mode is StreamMode.LEGACY
