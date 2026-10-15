"""Fast cancellation polling is separate from Context's full primary snapshot."""

from time import monotonic
from unittest.mock import Mock

import pytest
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline
from zebra_agent_worker.execution_events import ExecutionInterrupted

from tests.worker.test_recorder_append_guards import _recorder


def test_active_poll_is_fresh_scalar_and_still_checks_ownership(tmp_path, monkeypatch):
    stores, recorder, session_id = _recorder(tmp_path)
    scalar, owner = Mock(return_value=SessionStatus.RUNNING), Mock()
    recorder._execution_status_reader = scalar
    recorder._ownership_check = owner
    full = Mock(side_effect=AssertionError("active poll must not read full projection"))
    monkeypatch.setattr(stores.sessions, "get_session", full)
    assert recorder.require_active_execution() is None
    assert recorder.require_active_execution() is None
    assert scalar.call_args_list == [((session_id,),), ((session_id,),)]
    assert owner.call_count == 2
    owner.side_effect = LeaseLostError("lease lost")
    with pytest.raises(LeaseLostError, match="lease lost"):
        recorder.require_active_execution()


@pytest.mark.parametrize("status", [SessionStatus.CANCELLED, SessionStatus.SUSPENDED,
                                   SessionStatus.FAILED, SessionStatus.COMPLETED])
def test_terminal_status_preserves_original_fresh_session_error(tmp_path, monkeypatch, status):
    stores, recorder, _ = _recorder(tmp_path)
    recorder._execution_status_reader = Mock(return_value=status)
    fresh = recorder.session.model_copy(update={"status": status})
    full = Mock(return_value=fresh)
    monkeypatch.setattr(stores.sessions, "get_session", full)
    with pytest.raises(ExecutionInterrupted) as caught:
        recorder.require_active_execution()
    assert caught.value.session is fresh
    full.assert_called_once()


def test_scalar_missing_or_io_error_fails_closed(tmp_path):
    _, recorder, _ = _recorder(tmp_path)
    recorder._execution_status_reader = Mock(return_value=None)
    with pytest.raises(ValueError, match="control projection is missing"):
        recorder.require_active_execution()
    recorder._execution_status_reader.side_effect = TimeoutError("bounded read")
    with pytest.raises(TimeoutError, match="bounded read"):
        recorder.require_active_execution()


def test_context_and_local_poll_keep_full_reader(tmp_path, monkeypatch):
    stores, recorder, session_id = _recorder(tmp_path)
    original = stores.sessions.get_session
    full = Mock(wraps=original)
    monkeypatch.setattr(stores.sessions, "get_session", full)
    assert recorder.require_active_execution() is None
    assert full.call_count == 1
    recorder._execution_status_reader = Mock(side_effect=AssertionError("Context needs full row"))
    assert recorder.read_active_session() == original(session_id)
    assert full.call_count == 2


def test_scalar_read_does_not_extend_inherited_deadline(tmp_path):
    _, recorder, _ = _recorder(tmp_path)
    deadline = monotonic() + 0.2

    def read(session_id):
        assert current_task_io_deadline() == deadline
        return SessionStatus.RUNNING

    recorder._execution_status_reader = read
    with task_io_deadline(deadline):
        recorder.require_active_execution()
    assert current_task_io_deadline() is None


def test_cloud_factory_composes_bounded_scalar_read(tmp_path):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_core.domain.leases import LeaseFence, WorkerLease
    from agent_storage import postgres_control_plane_stores
    from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory

    _, local, session_id = _recorder(tmp_path)
    scope = OpaqueAuthorityScope(authority_issuer="https://probe.example", namespace_id="one")
    stores = postgres_control_plane_stores(
        "postgresql://localhost/unused", deployment_namespace="one",
        memory_cursor_signing_key=b"x" * 32, artifact_objects=Mock(),
        history_scope=scope, continuation_scope=scope,
    )
    now = datetime.now(UTC)
    lease = WorkerLease(
        session_id=session_id,
        fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="probe"),
        acquired_at=now, heartbeat_at=now, expires_at=now + timedelta(seconds=30),
    )
    from contextlib import nullcontext

    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {"status": "running"}

    def connect():
        deadline = current_task_io_deadline()
        assert deadline is not None and 0 < deadline - monotonic() <= 2
        return nullcontext(connection)

    stores.sessions._database.connect_task_io = connect
    owner = Mock()
    recorder = WorkerProjectionRecorderFactory(
        stores=stores, model_call_indexer=Mock(), tool_run_indexer=Mock(),
        transaction=Mock(), deployment_namespace="one",
    ).build(session=local.session, workspace=local.workspace, lease=lease, ownership_check=owner)
    assert recorder.require_active_execution() is None
    assert connection.execute.call_count == 1
    owner.assert_called_once_with()


def test_native_pg_scalar_stop_reaps_both_parallel_tls_requests(tmp_path, monkeypatch):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep
    from uuid import uuid4

    import psycopg
    from agent_runtime.harness import LocalToolGateway
    from agent_storage.postgres.projections import PostgresProjectionStore, _session_values
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from tests.agent_runtime.test_crawl_source_http import call, native_tls_source
    from tests.agent_runtime.test_native_network_cancellation import (
        native_connect_proxy,
        observe_children,
    )

    configured = os.environ.get("ZEBRA_CONTROL_READ_TEST_DSN")
    if not configured:
        pytest.skip("set ZEBRA_CONTROL_READ_TEST_DSN to isolated web_control_scratch")
    settings = conninfo_to_dict(configured)
    assert settings["dbname"] == "web_control_scratch"
    assert settings["host"] in {"127.0.0.1", "localhost"}
    schema = "control_tls_" + uuid4().hex
    _, recorder, session_id = _recorder(tmp_path)
    with psycopg.connect(configured, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(configured, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(dsn) as connection:
            connection.execute("CREATE TABLE session_projections (deployment_namespace TEXT, "
                               "session_id UUID,title TEXT,status TEXT,created_at TIMESTAMPTZ, "
                               "updated_at TIMESTAMPTZ,current_sequence BIGINT,namespace_id TEXT, "
                               "approval_context_json JSONB,clarification_context_json JSONB, "
                               "task_plan_json JSONB,PRIMARY KEY(deployment_namespace,session_id))")
            connection.execute("INSERT INTO session_projections VALUES "
                               "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                               _session_values("one", recorder.session))
        store = PostgresProjectionStore(dsn, deployment_namespace="one")
        recorder._projection_store = store
        recorder._execution_status_reader = store.get_session_status
        children = observe_children(monkeypatch)
        with native_connect_proxy(monkeypatch) as target:
            with native_tls_source(tmp_path, monkeypatch, "drip", on_listen=target.append) as (
                requests, entered, closed, release, writes,
            ):
                gateway = LocalToolGateway(tmp_path, trusted_local=True,
                                           network_cancellation_check=recorder.require_active_execution)
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        futures = [
                            pool.submit(gateway.execute, call("web.fetch")) for _ in range(2)
                        ]
                        deadline = monotonic() + 5
                        while len(requests) < 2 and monotonic() < deadline:
                            sleep(0.01)
                        assert len(requests) == 2 and entered.is_set()
                        started = monotonic()
                        with psycopg.connect(dsn) as connection:
                            connection.execute("UPDATE session_projections SET status='cancelled' "
                                               "WHERE deployment_namespace=%s AND session_id=%s",
                                               ("one", session_id))
                        for future in futures:
                            with pytest.raises(ExecutionInterrupted) as stopped:
                                future.result(timeout=3)
                            assert stopped.value.session.status is SessionStatus.CANCELLED
                        assert monotonic() - started < 2
                        assert closed.wait(1)
                        assert len(children) == 2
                        assert all(child.poll() is not None for child in children)
                        assert all(child.stdout.closed and child.stdin.closed for child in children)
                finally:
                    release.set()
                    gateway.close()
    finally:
        with psycopg.connect(configured, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
