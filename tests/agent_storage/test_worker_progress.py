"""Real SQLite Run progress: canonical pages, atomic CAS and bounded reads."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
)
from agent_core.ports.worker_progress import WorkerProgressScope
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore


def seed_progress(database: Path):
    segment = new_session_id()
    events = SQLiteEventStore(database)
    first = SessionEvent.create(
        session_id=segment,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Run progress"},
    )
    events.append(first)
    SQLiteProjectionStore(database).save_session(rebuild_session([first]))
    tasks = SQLiteAgentTaskStore(database)
    task = tasks.ensure_for_session(segment)
    while not tasks.backfill_event_positions(task.task_id):
        pass
    while not tasks.backfill_replay_headers(task.task_id):
        pass
    command = SessionCommand(
        session_id=segment,
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key="progress:run",
        payload={"run_id": "host-run"},
    )
    anchor = SessionEvent.create(
        session_id=segment,
        sequence=1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )
    events.append(anchor)
    scope = WorkerProgressScope("local", task.task_id, "host-run", anchor.event_id, 1)
    return tasks, events, scope


def append_progress(events, scope, kind, payload):
    event = SessionEvent.create(
        session_id=scope.task_id,
        sequence=len(events.list_for_session(scope.task_id)),
        event_type=kind,
        actor=EventActor.HARNESS,
        payload=payload,
    )
    events.append(event)
    return event


def output_payload(*, output="public:2:found", attempt=2, content="Verified record"):
    return {
        "attempt_number": attempt,
        "output_id": output,
        "kind": "result",
        "phase": "evidence",
        "origin": "system",
        "content": content,
        "meaningful": True,
        "evidence_basis": "verified_result",
        "evidence_refs": ["read:1"],
    }


def test_missing_progress_is_read_only_and_explicit_preparation_restores(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "progress.sqlite")
    statements = []
    connect = tasks._database.connect

    def traced():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    tasks._database.connect = traced
    with pytest.raises(CheckpointNotReady):
        tasks.read_worker_progress(scope)
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )
    assert not any("SELECT *" in sql or "state_json" in sql for sql in statements)
    append_progress(events, scope, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 2})
    append_progress(events, scope, EventType.PUBLIC_OUTPUT, output_payload())
    head = tasks.advance_worker_progress(scope, tasks.read_event_page(scope.task_id, 0))
    assert head.through_sequence == 3 and head.state.attempt_number == 2
    assert head.state.published_count == 1 and head.state.result_published
    reopened = SQLiteAgentTaskStore(tmp_path / "progress.sqlite")
    assert reopened.read_worker_progress(scope) == head
    assert reopened.worker_output_published(scope, "public:2:found")
    assert reopened.worker_receipts_covered(scope, ("read:1", "missing")) == frozenset({"read:1"})


def test_duplicate_frontier_cannot_replace_committed_state(tmp_path):
    tasks, _, scope = seed_progress(tmp_path / "cas.sqlite")
    page = tasks.read_event_page(scope.task_id, 0)
    expected = tasks.advance_worker_progress(scope, page)
    with pytest.raises(CheckpointStale, match="CAS"):
        tasks.advance_worker_progress(scope, page)
    assert tasks.read_worker_progress(scope) == expected


def test_two_concurrent_workers_have_one_atomic_frontier_winner(tmp_path):
    tasks, _, scope = seed_progress(tmp_path / "race.sqlite")
    page = tasks.read_event_page(scope.task_id, 0)

    def advance():
        try:
            return tasks.advance_worker_progress(scope, page).through_sequence
        except CheckpointStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: advance(), range(2)))
    assert sorted(results, key=str) == [1, "stale"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace", "foreign"),
        ("run_id", "forged"),
        ("version", "unknown"),
        ("anchor_sequence", 0),
    ],
)
def test_scope_is_validated_against_native_run(tmp_path, field, value):
    tasks, _, scope = seed_progress(tmp_path / "identity.sqlite")
    with pytest.raises((CheckpointConflict, CheckpointNotReady, ValueError)):
        tasks.advance_worker_progress(
            replace(scope, **{field: value}), tasks.read_event_page(scope.task_id, 0)
        )


def test_changed_source_payload_and_changed_output_identity_roll_back(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "source.sqlite")
    append_progress(events, scope, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 2})
    append_progress(events, scope, EventType.PUBLIC_OUTPUT, output_payload())
    page = tasks.read_event_page(scope.task_id, 0)
    entries = list(page.events)
    entries[-1] = replace(
        entries[-1],
        event=entries[-1].event.model_copy(update={"payload": output_payload(content="forged")}),
    )
    with pytest.raises(CheckpointConflict, match="canonical"):
        tasks.advance_worker_progress(scope, replace(page, events=tuple(entries)))
    with pytest.raises(CheckpointNotReady):
        tasks.read_worker_progress(scope)
    committed = tasks.advance_worker_progress(scope, page)
    append_progress(events, scope, EventType.PUBLIC_OUTPUT, output_payload(content="changed"))
    with pytest.raises(CheckpointConflict, match="identity changed"):
        tasks.advance_worker_progress(scope, tasks.read_event_page(scope.task_id, 3))
    assert tasks.read_worker_progress(scope) == committed


def test_one_run_does_not_consume_the_next_command(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "boundary.sqlite")
    command = SessionCommand(
        session_id=scope.task_id,
        kind=SessionCommandKind.RUN,
        expected_revision=1,
        idempotency_key="next",
        payload={"run_id": "next"},
    )
    append_progress(events, scope, EventType.SESSION_COMMAND_ACCEPTED, command.event_payload())
    with pytest.raises(CheckpointConflict, match="boundary"):
        tasks.advance_worker_progress(scope, tasks.read_event_page(scope.task_id, 0))
    assert (
        tasks.advance_worker_progress(
            scope, tasks.read_event_page(scope.task_id, 0, through_sequence=1)
        ).through_sequence
        == 1
    )
