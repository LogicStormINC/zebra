"""Confirmed source survives derived checkpoint timeout; unknown writes never replay."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_core.application.session_projection import rebuild_session
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.ports.worker_progress import WorkerProgressTimeout
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result
from zebra_agent_worker.progress_recovery import recover_worker_progress


def check(path: Path) -> None:
    session = new_session_id()
    events = SQLiteEventStore(path)
    first = SessionEvent.create(
        session_id=session,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "check"},
    )
    events.append(first)
    SQLiteProjectionStore(path).save_session(rebuild_session([first]))
    tasks = SQLiteAgentTaskStore(path)
    task = tasks.ensure_for_session(session)
    while not tasks.backfill_event_positions(task.task_id):
        pass
    while not tasks.backfill_replay_headers(task.task_id):
        pass
    command = SessionCommand(
        session_id=session,
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key="check",
        payload={"run_id": "check"},
    )
    anchor = SessionEvent.create(
        session_id=session,
        sequence=1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
    )
    events.append(anchor)
    recovery = recover_worker_progress(
        tasks=tasks, namespace="local", session_id=session, ownership_check=lambda: None
    )
    sequence = 1
    rows = []

    def append(draft):
        nonlocal sequence
        sequence += 1
        events.append(
            SessionEvent.create(
                session_id=session,
                sequence=sequence,
                event_type=draft.event_type,
                actor=draft.actor,
                payload=draft.payload,
            )
        )
        rows.append(draft)

    sink = ProgressiveEventSink(
        recovery.persist_with(append),
        user_input="读取信息",
        policy=PublicOutputPolicy(),
        recovery_state=recovery.head.state,
        output_published=recovery.output_published,
    )
    original = tasks.advance_worker_progress
    fired = False

    def timeout_after_commentary(*args, **kwargs):
        nonlocal fired
        if rows and rows[-1].event_type is EventType.PUBLIC_OUTPUT and not fired:
            fired = True
            raise TimeoutError("checkpoint response lost")
        return original(*args, **kwargs)

    payload = {
        "attempt_number": 1,
        "model_call_id": "model1",
        "assistant_message": "公开进度",
        "response_stage": "tool_loop",
    }
    with patch.object(tasks, "advance_worker_progress", timeout_after_commentary):
        sink(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, payload))
    assert fired and len(rows) == 2
    assert recovery.head.state.pending_commentary is not None
    sink(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"attempt_number": 1, "model_call_id": "model2"},
        )
    )
    assert recovery.head.state.pending_commentary is None
    assert recovery.head.state.commentary_reserved_count == 1
    assert recovery.head.state.commentary_published_count == 1
    sink(
        HarnessEventDraft(
            EventType.MODEL_RESPONSE_RECEIVED,
            EventActor.HARNESS,
            {**payload, "model_call_id": "model2"},
        )
    )
    assert len([r for r in rows if r.event_type is EventType.PUBLIC_OUTPUT]) == 2
    assert recovery.head.state.commentary_reserved_count == 2
    assert sink._commentary.reserved == 2
    sink.close()

    def unknown(draft):
        append(draft)
        raise TimeoutError("unknown canonical commit")

    error = WorkerProgressTimeout("canonical_append", canonical_committed=False)
    result = exception_attempt_result(error, error_metadata(error, None, None))
    assert result.summary == "execution progress storage unavailable"
    assert result.metadata["stop_reason"] == "execution_progress_unavailable"

    before = len(rows)
    try:
        recovery.persist_with(unknown)(
            HarnessEventDraft(
                EventType.MODEL_REQUEST_STARTED,
                EventActor.HARNESS,
                {"attempt_number": 1, "model_call_id": "unknown"},
            )
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("unknown canonical write was swallowed")
    assert len(rows) == before + 1
    print("confirmed-source deferral and exact-once repair pass; unknown commit propagates")


def check_other_publishers() -> None:
    for confirmed in (True, False):

        def fail(_draft, confirmed=confirmed):
            raise WorkerProgressTimeout("checkpoint", canonical_committed=confirmed)

        progress = ProgressiveEventSink(fail, user_input="check", policy=PublicOutputPolicy())
        progress._active.add("model:pending")
        progress._wait_elapsed(progress._timer_generation)
        assert (progress._timer_error is None) is confirmed
        assert progress._published_count == int(confirmed)
        progress._timer_error = None
        event = HarnessEventDraft(
            EventType.TOOL_EXECUTION_FAILED, EventActor.TOOL, {"tool_call_id": "receipt"}
        )
        try:
            progress.observe_operation_result(event)
        except WorkerProgressTimeout:
            assert not confirmed
        else:
            assert confirmed
        progress.close()
    print("timer and store-owned effect observation retain unknown-write failures")


with TemporaryDirectory() as directory:
    check(Path(directory) / "progress.sqlite")

check_other_publishers()
