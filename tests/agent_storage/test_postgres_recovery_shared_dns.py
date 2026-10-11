"""Recovery composition shares addresses, never authority or live connections."""

import time
from unittest.mock import Mock

import psycopg
import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_storage.postgres import task_io
from agent_storage.postgres.command_read_state_migration import COMMAND_READ_STATE_MIGRATION
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.projections import PostgresProjectionStore
from agent_storage.postgres.session_recovery import PostgresSessionRecoveryStore
from agent_storage.postgres.session_recovery_migration import SESSION_RECOVERY_MIGRATION
from agent_storage.postgres.task_event_bytes_migration import TASK_EVENT_BYTES_MIGRATION
from agent_storage.postgres.task_io import TaskIoConnections
from agent_storage.postgres.workspaces import PostgresWorkspaceProjectionStore
from agent_storage.postgres_composition import postgres_control_plane_stores
from zebra_agent_worker.bounded_session_recovery import recover_cloud_session

from tests.agent_storage.test_postgres_task_io_shared import (
    native_catalog_dsn as _native_catalog_dsn,
)
from tests.worker.test_bounded_session_recovery import NS, seed

native_catalog_dsn = _native_catalog_dsn


def test_composed_recovery_adapters_share_one_inert_connector() -> None:
    scope = OpaqueAuthorityScope(authority_issuer="scratch", namespace_id="reader")
    stores = postgres_control_plane_stores(
        "postgresql://reader:diagnostic@localhost/scratch",
        deployment_namespace="recovery",
        memory_cursor_signing_key=b"s" * 32,
        artifact_objects=Mock(),
        history_scope=scope,
        continuation_scope=scope,
    )
    connector = stores.sessions._database._task_io
    assert isinstance(connector, TaskIoConnections)
    assert stores.workspaces._database._task_io is connector
    assert stores.session_recovery._database._task_io is connector
    assert connector._attempts == ()


def test_explicit_composition_connector_is_reused_without_connecting() -> None:
    dsn = "postgresql://reader:diagnostic@localhost/scratch"
    shared = TaskIoConnections(dsn)
    scope = OpaqueAuthorityScope(authority_issuer="scratch", namespace_id="reader")
    stores = postgres_control_plane_stores(
        dsn,
        deployment_namespace="recovery",
        memory_cursor_signing_key=b"s" * 32,
        artifact_objects=Mock(),
        history_scope=scope,
        continuation_scope=scope,
        task_io_connections=shared,
    )
    assert stores.sessions._database._task_io is shared
    assert stores.workspaces._database._task_io is shared
    assert stores.session_recovery._database._task_io is shared
    assert shared._attempts == ()


@pytest.mark.parametrize(
    "store_type",
    [PostgresProjectionStore, PostgresWorkspaceProjectionStore, PostgresSessionRecoveryStore],
)
def test_optional_connector_preserves_namespace_and_rejects_foreign_dsn(store_type) -> None:
    dsn = "postgresql://reader:diagnostic@localhost/scratch"
    connector = TaskIoConnections(dsn)
    first = store_type(dsn, deployment_namespace="one", task_io_connections=connector)
    second = store_type(dsn, deployment_namespace="two", task_io_connections=connector)
    assert first._database._task_io is second._database._task_io is connector
    assert first._database.deployment_namespace == "one"
    assert second._database.deployment_namespace == "two"
    with pytest.raises(ValueError, match="connection configuration"):
        store_type(
            "postgresql://reader:diagnostic@localhost/foreign",
            deployment_namespace="one",
            task_io_connections=connector,
        )
    assert connector._attempts == ()


def test_native_cold_recovery_uses_one_resolver_and_fresh_connections_under_two_seconds(
    native_catalog_dsn,
    monkeypatch,
) -> None:
    # Reuse the existing schema-scoped native recovery seed; never migrate an application DB.
    with psycopg.connect(native_catalog_dsn) as database:
        for migration in MIGRATIONS:
            if migration.version in {1, 2, 4, 6, 20, 23}:
                for statement in migration.statements:
                    database.execute(statement)
        for migration in (TASK_EVENT_BYTES_MIGRATION, SESSION_RECOVERY_MIGRATION):
            for statement in migration.statements:
                database.execute(statement)
        database.execute(COMMAND_READ_STATE_MIGRATION.statements[0])
    state = seed(native_catalog_dsn, count=12)
    scope = OpaqueAuthorityScope(authority_issuer="scratch", namespace_id="reader")
    stores = postgres_control_plane_stores(
        native_catalog_dsn,
        deployment_namespace=NS,
        memory_cursor_signing_key=b"s" * 32,
        artifact_objects=Mock(),
        history_scope=scope,
        continuation_scope=scope,
    )
    connections, children, backend_pids = [], [], []
    connect, spawn = TaskIoConnections.connect, task_io.subprocess.Popen

    def observe_connection(self, **kwargs):
        connection = connect(self, **kwargs)
        connections.append(connection)
        backend_pids.append(connection.info.backend_pid)
        return connection

    def observe_child(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(TaskIoConnections, "connect", observe_connection)
    monkeypatch.setattr(task_io.subprocess, "Popen", observe_child)
    started = time.monotonic()
    session, workspace, highwater = recover_cloud_session(
        state.session_id,
        stores.session_recovery,
        stores.sessions,
        stores.workspaces,
        authority=state.authority,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 2
    assert session.current_sequence == workspace.current_sequence == highwater == 11
    assert len(children) == 1
    assert len(connections) >= 6
    assert len(set(backend_pids)) == len(connections)
    assert len({connection.deadline for connection in connections}) == 1
    assert all(connection.closed for connection in connections)
    assert all(child.poll() == 0 for child in children)
    shared = stores.sessions._database._task_io
    assert (
        PostgresProjectionStore(
            native_catalog_dsn, deployment_namespace="foreign", task_io_connections=shared
        ).get_session(state.session_id)
        is None
    )
    assert (
        PostgresWorkspaceProjectionStore(
            native_catalog_dsn, deployment_namespace="foreign", task_io_connections=shared
        ).get_workspace(state.session_id)
        is None
    )
