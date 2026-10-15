"""One fresh namespaced scalar read, preserving custom full-reader semantics."""

import os
from contextlib import nullcontext
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.projections import PostgresProjectionStore
from agent_storage.postgres.task_io import task_io_deadline
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def test_scalar_control_read_uses_one_query_and_no_body_or_setup_statement() -> None:
    store = PostgresProjectionStore("postgresql://localhost/unused", deployment_namespace="one")
    connection = Mock()
    connection.execute.return_value.fetchone.side_effect = [
        {"status": "running"}, {"status": "cancelled"}, None, {"status": "corrupt"},
    ]
    store._database = SimpleNamespace(
        connect_task_io=Mock(return_value=nullcontext(connection)), deployment_namespace="one"
    )
    session_id = uuid4()
    assert store.get_session_status(session_id) is SessionStatus.RUNNING
    assert store.get_session_status(session_id) is SessionStatus.CANCELLED
    assert store.get_session_status(session_id) is None
    with pytest.raises(ValueError):
        store.get_session_status(session_id)
    assert connection.execute.call_count == 4
    for request in connection.execute.call_args_list:
        query, parameters = request.args
        assert query == ("SELECT status FROM session_projections "
                         "WHERE deployment_namespace=%s AND session_id=%s")
        assert parameters == ("one", session_id)


def test_status_does_not_bypass_custom_full_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PostgresProjectionStore("postgresql://localhost/unused", deployment_namespace="one")
    reader = Mock(side_effect=[SimpleNamespace(status=SessionStatus.SUSPENDED), None])
    monkeypatch.setattr(store, "get_session", reader)
    session_id = uuid4()
    assert store.get_session_status(session_id) is SessionStatus.SUSPENDED
    assert store.get_session_status(session_id) is None
    assert reader.call_count == 2


def test_native_status_freshness_namespace_and_lock_deadline() -> None:
    configured = os.environ.get("ZEBRA_CONTROL_READ_TEST_DSN")
    if not configured:
        pytest.skip("set ZEBRA_CONTROL_READ_TEST_DSN to isolated web_control_scratch")
    settings = conninfo_to_dict(configured)
    assert settings["dbname"] == "web_control_scratch"
    assert settings["host"] in {"127.0.0.1", "localhost"}
    schema, session_id = "control_" + uuid4().hex, uuid4()
    with psycopg.connect(configured, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(configured, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(dsn) as connection:
            connection.execute("CREATE TABLE session_projections (deployment_namespace TEXT, "
                               "session_id UUID,status TEXT,task_plan_json JSONB, "
                               "PRIMARY KEY(deployment_namespace,session_id))")
            connection.execute("INSERT INTO session_projections VALUES (%s,%s,%s,%s::jsonb)",
                               ("one", session_id, "running", '{"unrelated":"unparsed"}'))
        store = PostgresProjectionStore(dsn, deployment_namespace="one")
        assert store.get_session_status(session_id) is SessionStatus.RUNNING
        assert PostgresProjectionStore(dsn, deployment_namespace="other").get_session_status(
            session_id
        ) is None
        with psycopg.connect(dsn) as connection:
            connection.execute("UPDATE session_projections SET status='cancelled'")
        assert store.get_session_status(session_id) is SessionStatus.CANCELLED
        with psycopg.connect(dsn) as blocker:
            blocker.execute("LOCK session_projections IN ACCESS EXCLUSIVE MODE")
            started = monotonic()
            with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled,
                                psycopg.errors.LockNotAvailable)):
                with task_io_deadline(started + 0.2):
                    store.get_session_status(session_id)
            assert monotonic() - started < 0.8
        assert store.get_session_status(session_id) is SessionStatus.CANCELLED
    finally:
        with psycopg.connect(configured, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
