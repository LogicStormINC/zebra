"""Initial pure reads share one native snapshot; post-mutation checks remain fresh."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from zebra_agent_worker.execution_input_preparation import recover_execution_input_events

from tests.agent_storage.test_postgres_execution_inputs import inputs
from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn
from tests.stream_storage.telemetry import Telemetry, phase
from tests.worker.test_execution_input_frontier import setup_inputs

native_dsn = checkpoint_dsn


@pytest.fixture
def prepared(native_dsn):
    store, _, lease = inputs(native_dsn)
    store.advance(lease, store.read_page(lease, -1, 1))
    return store, store._tasks, lease


def test_native_ready_inputs_use_two_fresh_sockets_including_final_header(prepared):
    store, tasks, lease = prepared
    expected = list(store.read(lease).state.events)
    telemetry = Telemetry()
    with telemetry.installed(), phase("preparation"):
        assert recover_execution_input_events(store=store, tasks=tasks, lease=lease) == expected
    assert telemetry.calls["initial/preparation/new_pg_socket"] == 2


def test_interleaved_command_is_not_hidden_by_initial_snapshot(prepared, monkeypatch):
    from agent_storage import PostgresEventStore
    from agent_storage.postgres import agent_tasks

    store, tasks, lease = prepared
    source = PostgresEventStore(store._database._dsn, deployment_namespace=store.namespace)
    late = SessionEvent.create(
        session_id=lease.session_id,
        sequence=2,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "fresh input after the initial Task header"},
    )
    original, seen, injected = agent_tasks.read_task_header, [], False

    def header(*args, **kwargs):
        nonlocal injected
        result = original(*args, **kwargs)
        if not injected:
            injected = True
            source.append(late)
        return result

    original_head = store._head

    def head(connection, key):
        result = original_head(connection, key)
        seen.append(result.through_sequence)
        return result

    monkeypatch.setattr(agent_tasks, "read_task_header", header)
    monkeypatch.setattr(store, "_head", head)
    events = recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert seen[0] == 1 and late in events
    assert store.read(lease).through_sequence == 2


def test_native_batch_matches_individual_reads_and_unknown_membership_denies(prepared):
    store, tasks, lease = prepared
    task_id = tasks.task_id_for_session(lease.session_id)
    expected = tasks.read_task_header(task_id), store.read(lease)
    assert store.read_preparation(lease, tasks) == expected
    with pytest.raises(CheckpointNotReady, match="membership"):
        store.read_preparation(lease.model_copy(update={"session_id": SessionId(uuid4())}), tasks)


@pytest.mark.parametrize("hook", ["task", "read", "other_tasks", "namespace", "database"])
def test_custom_composition_preserves_original_read_path(prepared, monkeypatch, hook):
    store, tasks, lease = prepared
    if hook == "task":
        original = tasks.task_id_for_session
        monkeypatch.setattr(tasks, "task_id_for_session", lambda value: original(value))
    if hook == "read":
        original = store.read
        monkeypatch.setattr(store, "read", lambda value: original(value))
    if hook in {"namespace", "database"}:
        monkeypatch.setattr(
            tasks,
            "_database",
            SimpleNamespace(
                _dsn="different" if hook == "database" else store._database._dsn,
                deployment_namespace="different" if hook == "namespace" else store.namespace,
            ),
        )
    passed = SimpleNamespace() if hook == "other_tasks" else tasks
    assert store.read_preparation(lease, passed) is None
    if hook in {"task", "read"}:
        assert recover_execution_input_events(store=store, tasks=tasks, lease=lease)


def test_sqlite_and_old_ports_keep_the_original_path(tmp_path):
    tasks, _, lease, store = setup_inputs(tmp_path)
    assert store.read_preparation(lease, tasks) is None
    # An older third-party Port has no optional batch capability.
    old = SimpleNamespace(read=store.read, read_page=store.read_page, advance=store.advance)
    expected = recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert recover_execution_input_events(store=old, tasks=tasks, lease=lease) == expected
