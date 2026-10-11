"""Control cancellation must not wait indefinitely behind a canonical stream lock."""

from time import monotonic
from unittest.mock import Mock

import psycopg
import pytest
from agent_storage.postgres.direct_control import PostgresDirectControl

from tests.agent_storage.test_postgres_direct_control import NAMESPACE, SCOPE, WORKSPACE, _setup
from tests.agent_storage.test_postgres_direct_control import dsn as schema_fixture
from tests.agent_storage.test_postgres_direct_control import postgres_dsn as scratch_fixture

dsn = schema_fixture
postgres_dsn = scratch_fixture


def test_native_control_uses_bounded_connection_and_rolls_back_on_stream_timeout(dsn, monkeypatch):
    lease = _setup(dsn)
    control = PostgresDirectControl(dsn, deployment_namespace=NAMESPACE)
    monkeypatch.setattr(
        control._database, "connect", Mock(side_effect=AssertionError("unbounded connection"))
    )
    with psycopg.connect(dsn) as blocker:
        blocker.execute(
            "SELECT current_version FROM session_streams "
            "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
            (NAMESPACE, lease.session_id),
        )
        started = monotonic()
        with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
            control.cancel(lease.session_id, scope=SCOPE, workspace_ref=WORKSPACE)
        assert monotonic() - started < 2.7
    with psycopg.connect(dsn) as database:
        assert database.execute(
            "SELECT count(*) FROM session_events WHERE event_type='session_cancelled'"
        ).fetchone()[0] == 0
        assert database.execute(
            "SELECT count(*) FROM direct_control_operations"
        ).fetchone()[0] == 0
        assert database.execute(
            "SELECT released_at FROM worker_leases WHERE session_id=%s", (lease.session_id,)
        ).fetchone()[0] is None
    # Deadline cancellation leaves the operation retryable, without partial revocation.
    assert control.cancel(
        lease.session_id, scope=SCOPE, workspace_ref=WORKSPACE
    ).event.event_type.value == "session_cancelled"
