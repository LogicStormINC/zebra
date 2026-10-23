"""Run windows have identical body-free semantics on both storage adapters."""

from pathlib import Path

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
)

from tests.agent_storage.test_postgres_agent_tasks import _seed_session
from tests.agent_storage.test_postgres_agent_tasks import task_namespace as _namespace_fixture

task_namespace = _namespace_fixture


@pytest.fixture(params=["sqlite", "postgres"])
def header_store(request, tmp_path: Path):
    if request.param == "postgres":
        dsn = request.getfixturevalue("postgres_dsn")
        namespace = request.getfixturevalue("task_namespace")
        session = _seed_session(dsn, namespace, tmp_path / "headers", "Headers")
        events = PostgresEventStore(dsn, deployment_namespace=namespace)
        store = PostgresAgentTaskStore(dsn, deployment_namespace=namespace)
    else:
        database = tmp_path / "headers.sqlite"
        session = new_session_id()
        events = SQLiteEventStore(database)
        event = SessionEvent.create(
            session_id=session,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Headers"},
        )
        events.append(event)
        SQLiteProjectionStore(database).save_session(rebuild_session([event]))
        store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(session)
    assert store.backfill_replay_headers(task.task_id, limit=1)
    return store, events, task


def _command(
    events, task, *, kind="run", run="run-one", actor=EventActor.USER, key="public-command"
):
    sequence = events.list_for_session(task.active_segment_id)[-1].sequence + 1
    command = SessionCommand(
        session_id=task.active_segment_id,
        kind=SessionCommandKind(kind),
        expected_revision=sequence - 1,
        idempotency_key=f"{key}{sequence}",
        payload={"run_id": run} if run is not None else {},
    )
    event = SessionEvent.create(
        session_id=task.active_segment_id,
        sequence=sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=actor,
        payload=command.event_payload(),
    )
    events.append(event)
    return event


def test_body_free_run_lookup_matches_executable_precedence_and_exact_identity(header_store):
    store, events, task = header_store
    legacy = store.read_run_header(task.task_id, "run-one")
    assert legacy.legacy and legacy.anchor is None
    _command(events, task, kind="cancel")
    executable = _command(events, task)
    following = _command(events, task, run="run-two")
    header = store.read_run_header(task.task_id, "run-one")
    assert not header.legacy and not header.control_only
    assert header.anchor.event_id == executable.event_id
    assert header.start == executable.sequence and header.stop == following.sequence
    assert store.read_event_header(task.task_id, header.start) == header.anchor
    assert store.read_event_header(task.task_id, header.highwater + 1) is None
    unknown = store.read_run_header(task.task_id, "not-present")
    assert not unknown.legacy and unknown.anchor is None


def test_duplicate_executable_anchor_fails_explicitly(header_store):
    store, events, task = header_store
    _command(events, task)
    _command(events, task)
    with pytest.raises(ValueError, match="ambiguous"):
        store.read_run_header(task.task_id, "run-one")


def test_internal_wakeup_does_not_end_run_but_null_public_run_does(header_store):
    store, events, task = header_store
    first = _command(events, task)
    internal = _command(
        events, task, kind="resume", run=None, actor=EventActor.HARNESS, key="child-wakeup:"
    )
    assert store.read_event_header(task.task_id, internal.sequence).internal_continuation
    assert store.read_run_header(task.task_id, "run-one").stop is None
    public = _command(events, task, run=None)
    assert store.read_run_header(task.task_id, "run-one").stop == public.sequence
    frozen = store.read_run_header(task.task_id, "run-one", through_sequence=first.sequence)
    assert frozen.stop is None and frozen.highwater == first.sequence


def test_control_only_does_not_become_executable_and_header_has_no_body(header_store):
    store, events, task = header_store
    command = _command(events, task, kind="cancel")
    header = store.read_run_header(task.task_id, "run-one")
    assert header.control_only and header.anchor.event_id == command.event_id
    assert not hasattr(header.anchor, "event") and not hasattr(header.anchor, "payload")


@pytest.mark.parametrize("value", [True, -2, 10_000])
def test_header_rejects_untrusted_future_or_invalid_highwater(header_store, value):
    store, _, task = header_store
    with pytest.raises(ValueError):
        store.read_run_header(task.task_id, "run-one", through_sequence=value)


@pytest.mark.parametrize(
    "actor,run,internal",
    [
        (EventActor.HARNESS, None, True),
        (EventActor.USER, None, False),
        (EventActor.HARNESS, "different-run", False),
    ],
)
def test_approval_resume_only_trusted_null_run_continues_original(
    header_store, actor, run, internal
):
    store, events, task = header_store
    original = _command(events, task)
    resumed = _command(events, task, kind="resume", run=run, actor=actor, key="approval-resume:")
    header = store.read_event_header(task.task_id, resumed.sequence)
    assert header.internal_continuation is internal
    assert store.read_run_header(task.task_id, "run-one").stop == (
        None if internal else resumed.sequence
    )
    if internal:
        assert store.read_latest_run_header(task.task_id).anchor.event_id == original.event_id
