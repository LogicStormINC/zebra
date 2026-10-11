"""Request-local report deadline propagation without changing ordinary adapters."""
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from types import SimpleNamespace

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectVerificationStatus
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_storage.coverage_artifact_reader import CloudCoverageArtifactReader
from agent_storage.postgres.coverage_recovery_preparation import (
    CoverageRecoveryDeferred,
    RecoveryDeadlineConnection,
)
from agent_storage.postgres.database import (
    PostgresDatabase,
    current_postgres_deadline,
    postgres_deadline,
)

from tests.agent_storage.test_artifact_payload_reads import (
    PAYLOAD,
    MetadataStub,
    ObjectStub,
    _record,
)
from tests.worker.coverage_model_cloud_fixtures import dsn, postgres_dsn  # noqa: F401


def test_nested_scope_never_extends_and_thread_ordinary_calls_are_unaffected(monkeypatch):
    calls = []
    raw = SimpleNamespace()
    monkeypatch.setattr(
        "agent_storage.postgres.database.psycopg.connect",
        lambda *args, **kwargs: calls.append(kwargs) or raw,
    )
    database = PostgresDatabase("postgresql://localhost/test", deployment_namespace="test")
    deadline = monotonic() + 10
    with postgres_deadline(deadline):
        with postgres_deadline(deadline + 100) as effective:
            assert effective == deadline
            wrapped = database.connect()
            assert isinstance(wrapped, RecoveryDeadlineConnection)
            assert wrapped.deadline == deadline
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(current_postgres_deadline).result() is None
            assert pool.submit(database.connect).result() is raw
        assert "statement_timeout=" in calls[0]["options"]
        assert "connect_timeout" not in calls[1]
    assert current_postgres_deadline() is None
    with pytest.raises(RuntimeError), postgres_deadline(deadline):
        raise RuntimeError("scope failure")
    assert current_postgres_deadline() is None


def test_exhaustion_never_connects(monkeypatch):
    monkeypatch.setattr(
        "agent_storage.postgres.database.psycopg.connect",
        lambda *_args, **_kwargs: pytest.fail("must not connect"),
    )
    database = PostgresDatabase("postgresql://localhost/test", deployment_namespace="test")
    with postgres_deadline(monotonic() - 1), pytest.raises(CoverageRecoveryDeferred):
        database.connect()


def test_context_preserves_wrapper_and_expired_fetch_is_not_exposed():
    class Connection:
        exited = None

        def __enter__(self):
            return self

        def __exit__(self, kind, exc, traceback):
            self.exited = kind

        def execute(self, *_):
            return SimpleNamespace(fetchone=lambda: {"proof": True})

    raw = Connection()
    wrapper = RecoveryDeadlineConnection(raw, monotonic() + 10)
    with wrapper as entered:
        assert entered is wrapper
        cursor = entered.execute("SELECT 1")
        cursor.deadline = monotonic() - 1
        with pytest.raises(CoverageRecoveryDeferred):
            cursor.fetchone()
    wrapper.deadline = monotonic() - 1
    with pytest.raises(CoverageRecoveryDeferred):
        with wrapper:
            pass
    assert raw.exited is CoverageRecoveryDeferred


def test_bounded_objects_use_same_deadline_and_reject_version_race():
    record = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    metadata = MetadataStub(record)
    deadline = monotonic() + 10

    class Objects(ObjectStub):
        def read_version_verified_before(self, expectation, version, received):
            assert received == deadline
            body = super().read_version_verified(expectation, version)
            metadata.record = None
            return body

    objects = Objects(ArtifactObjectVerificationStatus.VERIFIED)
    reader = CloudCoverageArtifactReader(
        metadata, objects, deployment_namespace="tenant-a", session_id=record.session_id,
        deadline_monotonic=deadline,
    )
    with pytest.raises(ValueError, match="changed"):
        reader.read_payload_bytes_bounded(record.artifact_id, max_bytes=len(PAYLOAD))
    assert objects.read_count == 1


def test_native_sql_deadline_cancels_work_not_just_the_wait(dsn):  # noqa: F811
    import psycopg

    started = monotonic()
    with psycopg.connect(dsn) as connection:
        pid = connection.info.backend_pid
        wrapper = RecoveryDeadlineConnection(connection, monotonic() + 0.15)
        with pytest.raises(CoverageRecoveryDeferred):
            wrapper.execute("SELECT pg_sleep(3)")
        connection.rollback()
        with psycopg.connect(dsn) as observer:
            state = observer.execute(
                "SELECT state FROM pg_stat_activity WHERE pid=%s", (pid,)
            ).fetchone()
            assert state[0] == "idle"
        assert connection.execute("SELECT 1 AS alive").fetchone()[0] == 1
    assert monotonic() - started < 2
