"""Native bounded execution reads: batch SQL, no I/O locks, refusal before consumption."""
# ruff: noqa: F811

from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres.coverage_transactions import validate_write
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_work_unit
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts

from tests.agent_storage.test_coverage_artifact_batches import publish, writes
from tests.agent_storage.test_coverage_artifact_publication import (
    _authority,
    _replace_worker,
)
from tests.agent_storage.test_coverage_artifact_publication import publication as publication
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401


def facade(env, check=None):
    fence = env.fence
    def native():
        with env.metadata._database.connect() as connection:
            validate_write(connection, NAMESPACE, env.binding, fence)
    return CloudCoverageArtifacts(
        binding=env.binding, deployment_namespace=NAMESPACE, metadata=env.metadata,
        objects=env.objects, publisher=env.publisher, authority=lambda: _authority(env),
        check_authority=native if check is None else check, sync_events=lambda: None,
    )


def test_bounded_read_phase_sql_constant_and_no_transaction_during_objects(
    publication, monkeypatch, record_property,
):
    env, source = publication, facade(publication)
    phase = ContextVar("execution_read_test", default=False)
    queries, counts = [], []
    execute, read = psycopg.Connection.execute, env.objects.read_version_verified

    def counted(connection, query, *args, **kwargs):
        if phase.get():
            queries.append(str(query))
        return execute(connection, query, *args, **kwargs)

    def outside(*args, **kwargs):
        assert borrow_work_unit((env.dsn, NAMESPACE)) is None
        return read(*args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", counted)
    monkeypatch.setattr(env.objects, "read_version_verified", outside)
    for count in (1, 9):
        payloads = writes(env, count)
        records = publish(env, payloads)
        queries.clear()
        token = phase.set(True)
        try:
            with source.read_payload_scope(tuple(key for key, _ in payloads)) as reader:
                for record, (_, payload) in zip(records, payloads, strict=True):
                    stored = reader.get_payload(record.artifact_id)
                    assert stored.sha256 == record.reservation.sha256
                    assert reader.read_payload_bytes(record.artifact_id) == payload.payload
                    assert reader.get_payload(record.artifact_id).uri == record.uri
            counts.append(len(queries))
            assert sum("SELECT * FROM artifact_payload_metadata" in q for q in queries) == 2
        finally:
            phase.reset(token)
        with pytest.raises(RuntimeError, match="ended"):
            reader.get_payload(records[0].artifact_id)
    assert counts[0] == counts[1]
    record_property("prepared_phase_client_sql", counts)


@pytest.mark.parametrize("change", ["metadata", "replacement", "revocation", "expired"])
def test_post_read_change_refuses_before_phase_consumption(publication, monkeypatch, change):
    env, payloads = publication, writes(publication)
    if change == "expired":
        payloads = tuple((key, payload.model_copy(update={
            "created_at": datetime.now(UTC) - timedelta(hours=2),
        })) for key, payload in payloads)
    records = publish(env, payloads)
    check = Mock(side_effect=[None, ValueError("revoked")]) if change == "revocation" else None
    source, consumed = facade(env, check), False
    with pytest.raises((ValueError, LeaseLostError)):
        with source.read_payload_scope(tuple(key for key, _ in payloads)) as reader:
            assert reader.read_payload_bytes(records[0].artifact_id) == payloads[0][1].payload
            if change == "replacement":
                _replace_worker(env)
            elif change in {"metadata", "expired"}:
                with env.metadata._database.connect() as connection:
                    field = "file_name='changed'" if change == "metadata" else (
                        "retained_until=clock_timestamp() - interval '1 second'"
                    )
                    connection.execute(
                        f"UPDATE artifact_payload_metadata SET {field} "
                        "WHERE deployment_namespace=%s AND artifact_id=%s",
                        (NAMESPACE, records[0].artifact_id),
                    )
        consumed = True
    assert not consumed
    with pytest.raises(RuntimeError, match="ended"):
        reader.get_payload(records[0].artifact_id)


def test_read_phase_refuses_invalid_missing_foreign_and_writes(publication):
    env, source = publication, facade(publication)
    payloads = writes(env, 1)
    record = publish(env, payloads)[0]
    for invalid in ((), (record.artifact_id, record.artifact_id), ("invalid",),
                    tuple(ArtifactId(uuid4()) for _ in range(1001))):
        with pytest.raises(ValueError, match="identity set"):
            with source.read_payload_scope(invalid):
                pytest.fail("invalid read phase entered")
    missing = ArtifactId(uuid4())
    with source.read_payload_scope((record.artifact_id, missing)) as reader:
        assert reader.get_payload(missing) is None
        with pytest.raises(ValueError, match="identity set"):
            reader.get_payload(ArtifactId(uuid4()))
        with pytest.raises(ValueError, match="cannot publish"):
            reader.store_payload_immutable(env.payload, artifact_id=missing)
        with pytest.raises(ValueError, match="cannot publish"):
            reader.store_payloads_immutable(((missing, env.payload),))
    with postgres_work_unit(env.metadata._database):
        with source.read_payload_scope((record.artifact_id,)) as reader:
            assert reader is source  # Existing guarded proof, not prepared coalescing.
            assert reader.get_payload(record.artifact_id).uri == record.uri
