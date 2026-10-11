"""Exact Artifact reads retain the full projection oracle without listing siblings."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.session_artifact_read import (
    MAX_ARTIFACT_PROJECTION_BYTES,
    SessionArtifactReadUnavailableError,
)
from agent_storage import SQLiteArtifactStore, SQLiteModelCallStore, SQLiteToolRunStore
from agent_storage.artifact_object_reads import artifact_read_scope

from tests.api.test_artifact_download_deadline import (
    native_media as _native_media,
)
from tests.api.test_artifact_download_deadline import (
    native_media_dsn as _native_media_dsn,
)
from tests.api.test_artifact_download_deadline import (
    native_objects as _native_objects,
)
from tests.api.test_artifact_download_deadline import (
    postgres_dsn as _postgres_dsn,
)

native_media = _native_media
native_media_dsn = _native_media_dsn
native_objects = _native_objects
postgres_dsn = _postgres_dsn


@pytest.fixture
def sqlite_points(tmp_path):
    path = tmp_path / "points.sqlite"
    session = new_session_id()
    public_id = str(uuid4())
    SQLiteModelCallStore(path).upsert(
        ModelCallRecord(
            session_id=session,
            sequence=4,
            provider="native",
            model_name="model",
            assistant_message="answer " + "x" * 170 + " token=secret",
            tool_call_count=0,
            created_at=datetime.now(UTC),
        )
    )
    SQLiteToolRunStore(path).upsert(
        ToolRunRecord(
            session_id=session,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            output="ghp_1234567890abcdef",
            artifact_uri=f"artifact://{public_id}",
            created_at=datetime.now(UTC),
        )
    )
    store = SQLiteArtifactStore(path)
    return path, store, session, public_id, store.list_for_session(session)


def no_listing(*args, **kwargs):
    raise AssertionError("point lookup enumerated session history")


@pytest.mark.parametrize("key", ["model-call:4", "tool-run:5", "public"])
def test_sqlite_point_matches_full_redaction_oracle(sqlite_points, monkeypatch, key):
    _, store, session, public_id, oracle = sqlite_points
    monkeypatch.setattr(SQLiteModelCallStore, "list_for_session", no_listing)
    monkeypatch.setattr(SQLiteToolRunStore, "list_for_session", no_listing)
    monkeypatch.setattr(SQLiteArtifactStore, "list_for_session", no_listing)
    found = store.get_for_session(session, public_id if key == "public" else key)
    assert found == oracle[0 if key.startswith("model") else 1]
    assert found.preview_state["redacted"] is True


@pytest.mark.parametrize(
    "key",
    [
        "tool-run:0",
        "tool-run:-1",
        "tool-run:05",
        "model-call:+4",
        "tool-run: 5",
        "tool-run:9223372036854775808",
        pytest.param("tool-run:" + "9" * 5000, id="oversized-id"),
        "invalid",
    ],
)
def test_sqlite_missing_or_malformed_point_never_lists(sqlite_points, monkeypatch, key):
    _, store, session, _, _ = sqlite_points
    monkeypatch.setattr(SQLiteArtifactStore, "list_for_session", no_listing)
    assert store.get_for_session(session, key) is None


def test_sqlite_point_is_session_bound(sqlite_points):
    _, store, _, public_id, _ = sqlite_points
    assert store.get_for_session(new_session_id(), public_id) is None
    assert store.get_for_session(new_session_id(), "tool-run:5") is None


def test_sqlite_point_size_admission_precedes_body_fetch(sqlite_points, monkeypatch):
    path, store, session, public_id, _ = sqlite_points
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE tool_runs SET output = ? WHERE session_id = ? AND sequence = 5",
            ("证" * MAX_ARTIFACT_PROJECTION_BYTES, str(session)),
        )
        connection.commit()
    queries = []
    connect = store._database.connect

    def capture():
        connection = connect()
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(store._database, "connect", capture)
    with pytest.raises(SessionArtifactReadUnavailableError):
        store.get_for_session(session, public_id)
    assert len([q for q in queries if q.startswith("SELECT")]) == 1
    assert not any(q.startswith("SELECT session_id,") for q in queries)


@pytest.mark.parametrize("count", [1000, 10_000, 100_000])
def test_cold_sqlite_point_uses_covering_seek_and_no_read_dml(sqlite_points, count):
    path, _, session, public_id, _ = sqlite_points
    with closing(sqlite3.connect(path)) as connection:
        connection.executemany(
            "INSERT INTO tool_runs VALUES "
            "(?, ?, 'tests.run', 'executed', NULL, 'sibling', NULL, ?)",
            ((str(session), n + 10, datetime.now(UTC).isoformat()) for n in range(count)),
        )
        connection.commit()
    cold = SQLiteArtifactStore(path)
    steps = []

    class Counted(sqlite3.Connection):
        def set_progress_handler(self, callback, n):
            def counted():
                steps.append(n)
                return callback()

            super().set_progress_handler(counted, n)

    def connect():
        connection = sqlite3.connect(path, factory=Counted)
        connection.row_factory = sqlite3.Row
        connection.set_authorizer(
            lambda action, *args: sqlite3.SQLITE_DENY
            if action
            in {
                sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_CREATE_INDEX,
                sqlite3.SQLITE_CREATE_TABLE,
            }
            else sqlite3.SQLITE_OK
        )
        return connection

    cold._database.connect = connect
    assert cold.get_for_session(session, public_id).artifact_id == "tool-run:5"
    assert sum(steps) <= 300, f"cold point traversed {sum(steps)} SQLite VM steps"
    with closing(sqlite3.connect(path)) as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT sequence FROM tool_runs "
            "WHERE session_id = ? AND artifact_uri = ? ORDER BY sequence LIMIT 1",
            (str(session), f"artifact://{public_id}"),
        ).fetchall()
    assert any("COVERING INDEX tool_runs_artifact_point" in row[3] for row in plan)


def test_sqlite_source_size_and_body_share_one_snapshot(sqlite_points, monkeypatch):
    path, store, session, public_id, oracle = sqlite_points
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")

    class Appending(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            if sql.startswith("SELECT sequence,"):
                with closing(sqlite3.connect(path)) as writer:
                    writer.execute("UPDATE tool_runs SET output = 'new' WHERE sequence = 5")
                    writer.commit()
            return cursor

    def connect():
        connection = sqlite3.connect(path, factory=Appending)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(store._database, "connect", connect)
    assert store.get_for_session(session, public_id) == oracle[1]


def test_sqlite_point_lock_obeys_actual_deadline_and_closes(sqlite_points):
    path, store, session, _, _ = sqlite_points
    with closing(sqlite3.connect(path)) as lock:
        lock.execute("BEGIN EXCLUSIVE")
        started = monotonic()
        with pytest.raises(TimeoutError), artifact_read_scope(deadline=started + 0.05):
            store.get_for_session(session, "tool-run:5")
        assert monotonic() - started < 0.3
        lock.rollback()
    assert store.get_for_session(session, "tool-run:5") is not None


@pytest.mark.parametrize("public", [False, True])
def test_native_postgres_point_keeps_exact_event_and_namespace(
    native_media, native_media_dsn, monkeypatch, public
):
    from uuid import UUID

    from agent_core.domain.identifiers import SessionId
    from agent_storage import PostgresSessionArtifactReadStore

    _, _, task_id, public_id, sequence, _ = native_media
    session = SessionId(UUID(task_id))
    store = PostgresSessionArtifactReadStore(
        native_media_dsn, deployment_namespace="native-media-forwarding"
    )
    oracle = store.list_for_session(session)[0]
    monkeypatch.setattr(PostgresSessionArtifactReadStore, "list_for_session", no_listing)
    key = public_id if public else f"tool-run:{sequence}"
    assert store.get_for_session(session, key) == oracle
    assert oracle.source_event_id is not None
    assert store.get_for_session(new_session_id(), key) is None
    foreign = PostgresSessionArtifactReadStore(native_media_dsn, deployment_namespace="other")
    assert foreign.get_for_session(session, key) is None


def test_native_postgres_single_statement_size_admission_and_actual_task_io(
    native_media, native_media_dsn, monkeypatch
):
    from uuid import UUID

    import psycopg
    from agent_core.domain.identifiers import SessionId
    from agent_storage import PostgresSessionArtifactReadStore
    from agent_storage.postgres.task_io import TaskIoConnection, TaskIoConnections, task_io_deadline

    _, _, task_id, public_id, sequence, _ = native_media
    store = PostgresSessionArtifactReadStore(
        native_media_dsn, deployment_namespace="native-media-forwarding"
    )
    session = SessionId(UUID(task_id))
    connections, queries = [], []
    connect, execute = TaskIoConnections.connect, TaskIoConnection.execute

    def capture_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        assert isinstance(connection, TaskIoConnection)
        connections.append(connection)
        return connection

    def capture_execute(self, query, params=None, **kwargs):
        queries.append((query, params, self.deadline))
        return execute(self, query, params, **kwargs)

    monkeypatch.setattr(TaskIoConnections, "connect", capture_connect)
    monkeypatch.setattr(TaskIoConnection, "execute", capture_execute)
    deadline = monotonic() + 1
    with task_io_deadline(deadline):
        assert store.get_for_session(session, public_id).sequence == sequence
    assert len(queries) == 1
    query, parameters, actual = queries[0]
    assert "JOIN artifact_payload_metadata" in query and "p.event_id = m.event_id" in query
    assert "m.artifact_id = %s" in query and "p.artifact_uri = m.artifact_uri" in query
    assert parameters[-1] == UUID(public_id) and actual == deadline
    assert all(connection.closed for connection in connections)
    with psycopg.connect(native_media_dsn) as setup:
        setup.execute(
            "UPDATE tool_run_projections SET output=%s "
            "WHERE deployment_namespace=%s AND session_id=%s AND sequence=%s",
            ("证" * MAX_ARTIFACT_PROJECTION_BYTES, "native-media-forwarding", session, sequence),
        )
    with pytest.raises(SessionArtifactReadUnavailableError):
        store.get_for_session(session, public_id)
    assert all(connection.closed for connection in connections)


def test_native_postgres_point_lock_is_cancelled_and_backend_disappears(
    native_media, native_media_dsn, monkeypatch
):
    from uuid import UUID

    import psycopg
    from agent_core.domain.identifiers import SessionId
    from agent_storage import PostgresSessionArtifactReadStore
    from agent_storage.postgres.task_io import TaskIoConnections

    _, _, task_id, public_id, _, _ = native_media
    store = PostgresSessionArtifactReadStore(
        native_media_dsn, deployment_namespace="native-media-forwarding"
    )
    connections = []
    connect = TaskIoConnections.connect

    def captured(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append((connection, connection.info.backend_pid))
        return connection

    monkeypatch.setattr(TaskIoConnections, "connect", captured)
    with psycopg.connect(native_media_dsn) as lock:
        lock.execute("LOCK TABLE tool_run_projections IN ACCESS EXCLUSIVE MODE")
        started = monotonic()
        with pytest.raises((TimeoutError, psycopg.OperationalError)):
            with artifact_read_scope(deadline=started + 0.2):
                store.get_for_session(SessionId(UUID(task_id)), public_id)
        assert monotonic() - started < 0.6
        assert connections and all(connection.closed for connection, _ in connections)
    with psycopg.connect(native_media_dsn, autocommit=True) as verify:
        until = monotonic() + 1
        while verify.execute(
            "SELECT 1 FROM pg_stat_activity WHERE pid=ANY(%s)",
            ([pid for _, pid in connections],),
        ).fetchone():
            assert monotonic() < until, "point lookup backend survived actual cancellation"


def test_injected_list_only_source_never_falls_back_to_listing(sqlite_points, monkeypatch):
    path, _, session, public_id, _ = sqlite_points
    models, tools = SQLiteModelCallStore(path), SQLiteToolRunStore(path)
    monkeypatch.setattr(models, "list_for_session", no_listing)
    monkeypatch.setattr(tools, "list_for_session", no_listing)
    injected = SQLiteArtifactStore(models, tools)
    with pytest.raises(SessionArtifactReadUnavailableError, match="not configured"):
        injected.get_for_session(session, public_id)
