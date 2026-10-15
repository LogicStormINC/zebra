"""Execution-input identity belongs to the same fresh native transaction."""

from contextlib import contextmanager

import pytest
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage.execution_inputs import ExecutionInputStore
from agent_storage.postgres.database import PostgresDatabase

from tests.agent_storage.test_postgres_execution_inputs import inputs
from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn

native_dsn = checkpoint_dsn


def test_native_input_operations_resolve_membership_on_their_own_connection(
    native_dsn, monkeypatch,
):
    store, _, lease = inputs(native_dsn)
    original = store._database.connect_task_io
    backends = []

    @contextmanager
    def connect(*args, **kwargs):
        with original(*args, **kwargs) as connection:
            backends.append(connection.info.backend_pid)
            yield connection

    monkeypatch.setattr(store._database, "connect_task_io", connect)
    monkeypatch.setattr(
        store._tasks, "task_id_for_session",
        lambda *_: pytest.fail("membership escaped the input transaction"),
    )
    assert store.read(lease).through_sequence == -1
    page = store.read_page(lease, -1, 1)
    assert store.advance(lease, page).through_sequence == 1
    assert store.read(lease).through_sequence == 1
    assert len(backends) == len(set(backends)) == 4  # One new transaction/socket per operation.

    foreign = ExecutionInputStore(
        PostgresDatabase(native_dsn, deployment_namespace="foreign"),
        store._tasks, namespace="foreign", postgres=True,
    )
    with pytest.raises(CheckpointNotReady, match="membership"):
        foreign.read(lease)
