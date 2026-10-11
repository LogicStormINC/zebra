"""Bounded native proof pages retain exact row/Event identity and phase isolation."""
# ruff: noqa: F811

from contextvars import ContextVar
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import ArtifactId
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.coverage_artifacts import pinned_payload_row, read_artifact
from agent_storage.postgres.coverage_proof_prefetch import materialized_sources, prefetch_proof

from tests.agent_storage.test_coverage_artifact_batches import publish, writes
from tests.agent_storage.test_coverage_artifact_publication import publication as publication
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401
from tests.worker.test_coverage_prepared_reads import facade


def test_one_and_nine_exact_proofs_use_two_native_queries(
    publication, monkeypatch, record_property,
):
    env, source = publication, facade(publication)
    active = ContextVar("locked_proof_test", default=False)
    execute, queries, counts = psycopg.Connection.execute, [], []

    def counted(connection, query, *args, **kwargs):
        if active.get():
            queries.append(str(query))
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", counted)
    for count in (1, 9):
        records = publish(env, writes(env, count))
        with env.metadata._database.connect() as connection:
            with source._locked_proof_scope(
                connection, NAMESPACE, env.binding, derive=derive_semantic_observation,
            ) as reader:
                queries.clear()
                token = active.set(True)
                try:
                    prefetch_proof(reader, tuple(record.uri for record in records))
                    for record in records:
                        for _ in range(3):
                            native = pinned_payload_row(
                                reader, connection, NAMESPACE,
                                record.artifact_id, record.session_id,
                            )
                            assert native["event_id"] == record.event_binding.event_id
                            sources = materialized_sources(
                                reader, connection, NAMESPACE, env.binding, record.uri,
                                event_id=record.event_binding.event_id,
                            )
                            assert len(sources) == 1
                            assert sources[0]["event_id"] == record.event_binding.event_id
                            assert read_artifact(
                                reader, record.uri, record.reservation.sha256, record.session_id,
                            ) == f"object-{records.index(record)}".encode()
                    counts.append(len(queries))
                    assert len(queries) == 2
                finally:
                    active.reset(token)
        assert not reader._proof_events and not reader._proof_rows
        with pytest.raises(RuntimeError, match="ended"):
            prefetch_proof(reader, (records[0].uri,))
    assert counts == [2, 2]
    record_property("locked_page_client_sql", counts)


def test_missing_and_foreign_scope_refuse_and_unknown_deriver_falls_back(publication):
    env, source = publication, facade(publication)
    record = publish(env, writes(env, 1))[0]
    with env.metadata._database.connect() as connection:
        with source._locked_proof_scope(
            connection, NAMESPACE, env.binding, derive=derive_semantic_observation,
        ) as reader:
            with pytest.raises(ValueError, match="missing or foreign"):
                prefetch_proof(reader, (f"artifact://{ArtifactId(uuid4())}",))
            prefetch_proof(reader, (record.uri,))
            for conn, deployment, session in (
                (object(), NAMESPACE, env.binding.session_id),
                (connection, "foreign", env.binding.session_id),
                (connection, NAMESPACE, uuid4()),
            ):
                with pytest.raises(ValueError, match="identity conflicts"):
                    reader._native_materialized_sources(conn, deployment, session, record.uri)
        with source._locked_proof_scope(
            connection, NAMESPACE, env.binding, derive=lambda *_: None,
        ) as reader:
            prefetch_proof(reader, (record.uri,))
            assert not reader._proof_events and not reader._proof_rows
            assert len(materialized_sources(reader, connection, NAMESPACE, env.binding,
                                            record.uri)) == 1


def test_page_keeps_conflicting_uri_events_and_exit_revocation(publication):
    env, records = publication, publish(publication, writes(publication, 2))
    with env.metadata._database.connect() as connection:
        connection.execute(
            """UPDATE session_events SET payload=jsonb_set(payload,'{metadata,artifact_uri}',
               to_jsonb(%s::text)) WHERE deployment_namespace=%s AND event_id=%s""",
            (records[0].uri, NAMESPACE, records[1].event_binding.event_id),
        )
    check = Mock(side_effect=[None, ValueError("revoked")])
    source = facade(env, check)
    with pytest.raises(ValueError, match="revoked"):
        with env.metadata._database.connect() as connection:
            with source._locked_proof_scope(
                connection, NAMESPACE, env.binding, derive=derive_semantic_observation,
            ) as reader:
                prefetch_proof(reader, tuple(record.uri for record in records))
                sources = materialized_sources(reader, connection, NAMESPACE, env.binding,
                                               records[0].uri)
                assert len(sources) == 2  # Original canonical verifier must refuse this.
    assert not reader._proof_events and not reader._proof_rows
