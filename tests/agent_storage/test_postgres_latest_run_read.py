"""One native statement selects the latest executable Run and its exact metadata."""

from uuid import uuid4

import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage.postgres.task_replay_headers import read_latest_run_header, read_run_header

from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn
from tests.worker import test_model_commentary_native as native

native_dsn = checkpoint_dsn


@pytest.fixture
def state(native_dsn, monkeypatch):
    monkeypatch.setattr(native, "NS", "latest-run-" + uuid4().hex)
    return native.native_state(native_dsn)


def append_command(state, kind, run):
    payload = {"run_id": run}
    if kind is SessionCommandKind.MESSAGE:
        payload["content"] = "next public request"
    command = SessionCommand(
        session_id=state.session.session_id,
        kind=kind,
        expected_revision=state.session.current_sequence,
        idempotency_key=uuid4().hex,
        payload=payload,
    )
    state.append(
        HarnessEventDraft(
            EventType.SESSION_COMMAND_ACCEPTED, EventActor.USER, command.event_payload()
        )
    )


class CountingConnection:
    def __init__(self, connection):
        self.connection, self.calls = connection, 0

    def execute(self, statement, parameters=()):
        self.calls += 1
        return self.connection.execute(statement, parameters)


def test_native_latest_header_matches_explicit_run_in_one_statement(state):
    task = state.tasks.ensure_for_session(state.session.session_id).task_id
    with state.database.connect_task_io() as connection:
        expected = read_run_header(connection, native.NS, task, "commentary-run", None)
        counted = CountingConnection(connection)
        assert read_latest_run_header(counted, native.NS, task) == expected
        assert counted.calls == 1


@pytest.mark.parametrize(
    "kind", [SessionCommandKind.RUN, SessionCommandKind.MESSAGE, SessionCommandKind.CANCEL]
)
def test_native_latest_identity_and_metadata_follow_new_canonical_commands(state, kind):
    task = state.tasks.ensure_for_session(state.session.session_id).task_id
    before = state.tasks.read_latest_run_header(task)
    append_command(state, kind, "new-run")
    expected_run = "commentary-run" if kind is SessionCommandKind.CANCEL else "new-run"
    with state.database.connect_task_io() as connection:
        expected = read_run_header(connection, native.NS, task, expected_run, None)
        actual = read_latest_run_header(connection, native.NS, task)
    assert actual == expected and actual.highwater > before.highwater
    assert (actual.anchor.event_id == before.anchor.event_id) is (kind is SessionCommandKind.CANCEL)


def test_native_fresh_call_sees_replacement_but_existing_snapshot_is_consistent(state):
    task = state.tasks.ensure_for_session(state.session.session_id).task_id
    with state.database.connect_task_io() as snapshot:
        snapshot.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        previous = read_latest_run_header(snapshot, native.NS, task)
        append_command(state, SessionCommandKind.RUN, "replacement")
        assert read_latest_run_header(snapshot, native.NS, task) == previous
    assert state.tasks.read_latest_run_header(task).run_id == "replacement"


@pytest.mark.parametrize("run", [None, "", "   ", "r" * 257])
def test_native_missing_or_invalid_latest_identity_remains_rejected(state, run):
    task = state.tasks.ensure_for_session(state.session.session_id).task_id
    append_command(state, SessionCommandKind.RUN, run)
    exception = ValueError if isinstance(run, str) and len(run) > 256 else CheckpointNotReady
    with pytest.raises(exception):
        state.tasks.read_latest_run_header(task)


def test_native_namespace_and_unready_source_remain_fail_closed(state):
    task = state.tasks.ensure_for_session(state.session.session_id).task_id
    with state.database.connect_task_io() as connection:
        with pytest.raises(CheckpointNotReady):
            read_latest_run_header(connection, "foreign", task)
        connection.execute(
            "UPDATE agent_tasks SET event_position_state='validating' "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (native.NS, task),
        )
    with pytest.raises(CheckpointNotReady, match="positions"):
        state.tasks.read_latest_run_header(task)
