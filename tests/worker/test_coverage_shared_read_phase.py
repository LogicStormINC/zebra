"""Actual PG common consumer reads; object transport remains controlled fake S3."""
# ruff: noqa: F811

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseLostError
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_work_unit

from tests.agent_storage.test_coverage_artifact_batches import publish, writes
from tests.agent_storage.test_coverage_artifact_publication import _replace_worker
from tests.worker.test_coverage_prepared_reads import (  # noqa: F401
    NAMESPACE,
    dsn,
    facade,
    postgres_dsn,
    postgres_env,
    publication,
)


@pytest.mark.parametrize("known_digest", [False, True])
def test_shared_load_has_phase_and_physical_boundaries_without_io_transaction(
    publication,
    monkeypatch,
    known_digest,
    record_property,
):
    env, payloads = publication, writes(publication, 1)
    record = publish(env, payloads)[0]
    check = Mock()
    consumer = CoverageArtifacts(facade(env, check), env.binding.session_id, nullcontext())
    original, read = psycopg.Connection.execute, env.objects.read_version_verified
    queries = []

    def counted(connection, query, *args, **kwargs):
        queries.append(str(query))
        return original(connection, query, *args, **kwargs)

    def outside(*args, **kwargs):
        assert borrow_work_unit((env.dsn, NAMESPACE)) is None
        return read(*args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", counted)
    monkeypatch.setattr(env.objects, "read_version_verified", outside)
    arguments = dict(
        mime_type=record.reservation.mime_type,
        expected_digest=(record.reservation.sha256 if known_digest else None),
    )
    result = consumer.load_payload(
        record.artifact_id,
        record.reservation.kind,
        1024,
        datetime.now(UTC),
        **arguments,
    )
    assert result is not None and result[1] == payloads[0][1].payload
    assert check.call_count == 4
    assert sum("SELECT * FROM artifact_payload_metadata" in q for q in queries) == 2
    count = len(queries)
    queries.clear()
    check.reset_mock()
    # The prior guarded consumer remains the fallback, measured with the same input.
    assert (
        consumer._load_payload(
            record.artifact_id,
            record.reservation.kind,
            1024,
            datetime.now(UTC),
            **arguments,
        )
        == result
    )
    assert check.call_count == (2 if known_digest else 3)
    assert count <= len(queries)
    record_property("shared_read_client_sql", {"phase": count, "legacy": len(queries)})


@pytest.mark.parametrize("change", ["metadata", "replacement", "revocation", "expired"])
def test_shared_load_exit_refuses_before_result_is_consumed(publication, monkeypatch, change):
    env, payloads = publication, writes(publication, 1)
    if change == "expired":
        payloads = tuple(
            (
                key,
                payload.model_copy(
                    update={
                        "created_at": datetime.now(UTC) - timedelta(hours=2),
                    }
                ),
            )
            for key, payload in payloads
        )
    record = publish(env, payloads)[0]
    revoked = False
    fence = env.fence

    def current():
        if revoked and change == "revocation":
            raise ValueError("revoked")
        with env.metadata._database.connect() as connection:
            from agent_storage.postgres.coverage_transactions import validate_write

            validate_write(connection, NAMESPACE, env.binding, fence)

    consumer = CoverageArtifacts(facade(env, current), env.binding.session_id, nullcontext())
    read = env.objects.read_version_verified

    def changed(*args, **kwargs):
        nonlocal revoked
        body = read(*args, **kwargs)
        if change == "replacement":
            _replace_worker(env)
        elif change in {"metadata", "expired"}:
            field = (
                "file_name='changed'"
                if change == "metadata"
                else "retained_until=clock_timestamp() - interval '1 second'"
            )
            with env.metadata._database.connect() as connection:
                connection.execute(
                    f"UPDATE artifact_payload_metadata SET {field} "
                    "WHERE deployment_namespace=%s AND artifact_id=%s",
                    (NAMESPACE, record.artifact_id),
                )
        revoked = True
        return body

    monkeypatch.setattr(env.objects, "read_version_verified", changed)
    consumed = False
    with pytest.raises((CoverageRefusedError, LeaseLostError)):
        consumer.load_payload(
            record.artifact_id,
            record.reservation.kind,
            1024,
            datetime.now(UTC),
            mime_type=record.reservation.mime_type,
        )
        consumed = True
    assert not consumed


def test_missing_shared_read_revalidates_absence_before_return(publication):
    env, payloads = publication, writes(publication, 1)
    calls = 0

    def insert_at_exit():
        nonlocal calls
        calls += 1
        if calls == 2:
            publish(env, payloads)

    consumer = CoverageArtifacts(
        facade(env, insert_at_exit),
        env.binding.session_id,
        nullcontext(),
    )
    with pytest.raises(CoverageRefusedError):
        consumer.load_payload(
            payloads[0][0],
            env.payload.kind,
            1024,
            datetime.now(UTC),
            mime_type=env.payload.mime_type,
        )
    consumer = CoverageArtifacts(facade(env), env.binding.session_id, nullcontext())
    assert (
        consumer.load_payload(ArtifactId(uuid4()), env.payload.kind, 1024, datetime.now(UTC))
        is None
    )


def test_owned_transaction_common_loader_retains_guarded_fallback(publication, monkeypatch):
    env, payloads = publication, writes(publication, 1)
    record = publish(env, payloads)[0]
    checks = Mock()
    consumer = CoverageArtifacts(facade(env, checks), env.binding.session_id, nullcontext())
    read = env.objects.read_version_verified

    def owned(*args, **kwargs):
        assert borrow_work_unit((env.dsn, NAMESPACE)) is not None
        return read(*args, **kwargs)

    monkeypatch.setattr(env.objects, "read_version_verified", owned)
    with postgres_work_unit(env.metadata._database):
        loaded = consumer.load_payload(
            record.artifact_id,
            record.reservation.kind,
            1024,
            datetime.now(UTC),
            mime_type=record.reservation.mime_type,
        )
        assert loaded is not None and loaded[1] == payloads[0][1].payload
        assert checks.call_count == 3  # Not a coalesced/unlocked read guarantee.
    assert borrow_work_unit((env.dsn, NAMESPACE)) is None


def test_miscomposed_deployment_refuses_before_authority_or_sql(publication, monkeypatch):
    env, payloads = publication, writes(publication, 1)
    record = publish(env, payloads)[0]
    check = Mock()
    source = facade(env, check)
    source.metadata = PostgresCloudArtifactPayloadStore(
        env.dsn,
        deployment_namespace="different-deployment",
    )
    consumer = CoverageArtifacts(source, env.binding.session_id, nullcontext())
    execute = Mock(side_effect=AssertionError("cross-deployment SQL"))
    monkeypatch.setattr(psycopg.Connection, "execute", execute)
    with pytest.raises(CoverageRefusedError):
        consumer.load_payload(
            record.artifact_id,
            record.reservation.kind,
            1024,
            datetime.now(UTC),
            mime_type=record.reservation.mime_type,
        )
    check.assert_not_called()
    execute.assert_not_called()
