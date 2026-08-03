from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_core.ports import CloudControlPlane
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_storage import (
    ControlPlaneStores,
    IdempotencyConflictError,
    PostgresControlPlaneStores,
    apply_postgres_migrations,
    postgres_control_plane_stores,
    sqlite_control_plane_stores,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo


class _ObjectReader:
    def verify(self, expectation: object) -> object:
        raise AssertionError(
            f"payload object should not be read in composition test: {expectation}"
        )

    def read_version_verified(self, expectation: object, object_version: str) -> bytes:
        raise AssertionError(f"payload object should not be read: {expectation}, {object_version}")


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str):
    schema = f"control_plane_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_cloud_contract_is_separate_from_local_control_plane(tmp_path) -> None:
    local = sqlite_control_plane_stores(tmp_path / "local.sqlite")
    assert isinstance(local, ControlPlaneStores)
    assert not isinstance(local, CloudControlPlane)
    assert PostgresControlPlaneStores.__name__ == "PostgresControlPlaneStores"


def test_postgres_composition_fails_closed_for_required_cloud_dependencies(dsn: str) -> None:
    scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="scope")
    with pytest.raises(ValueError, match="signing key"):
        postgres_control_plane_stores(
            dsn,
            deployment_namespace="namespace",
            memory_cursor_signing_key=b"short",
            artifact_objects=_ObjectReader(),
            history_scope=scope,
            continuation_scope=scope,
        )
    with pytest.raises(ValueError, match="object reader"):
        postgres_control_plane_stores(
            dsn,
            deployment_namespace="namespace",
            memory_cursor_signing_key=b"k" * 32,
            artifact_objects=None,  # type: ignore[arg-type]
            history_scope=scope,
            continuation_scope=scope,
        )


def test_postgres_composition_is_namespace_scoped_and_round_trips_shared_records(
    dsn: str,
) -> None:
    first_namespace = f"namespace-{uuid4()}"
    second_namespace = f"namespace-{uuid4()}"
    history_scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="history")
    continuation_scope = OpaqueAuthorityScope(
        authority_issuer="issuer", namespace_id="continuation"
    )
    first = postgres_control_plane_stores(
        dsn,
        deployment_namespace=first_namespace,
        memory_cursor_signing_key=b"k" * 32,
        artifact_objects=_ObjectReader(),
        history_scope=history_scope,
        continuation_scope=continuation_scope,
    )
    second = postgres_control_plane_stores(
        dsn,
        deployment_namespace=second_namespace,
        memory_cursor_signing_key=b"k" * 32,
        artifact_objects=_ObjectReader(),
        history_scope=history_scope,
        continuation_scope=continuation_scope,
    )
    assert isinstance(first, CloudControlPlane)
    assert first.deployment_namespace == first_namespace
    probe_session = SessionId(uuid4())
    assert first.model_tool_projections.list_model_calls(probe_session) == []
    assert first.model_tool_projections.list_tool_runs(probe_session) == []

    created_at = datetime(2026, 8, 3, tzinfo=UTC)
    record = IdempotencyRecord(
        action="session.create",
        idempotency_key="request-1",
        request_hash="hash-1",
        status_code=201,
        response_body={"session_id": "one"},
        created_at=created_at,
    )
    assert first.idempotency.save(record) == record
    assert (
        first.idempotency.get(action=record.action, idempotency_key=record.idempotency_key)
        == record
    )
    with pytest.raises(IdempotencyConflictError):
        first.idempotency.save(replace(record, request_hash="hash-2"))
    assert (
        second.idempotency.get(action=record.action, idempotency_key=record.idempotency_key) is None
    )

    audit = DeliveryAuditRecord(
        session_id=SessionId(uuid4()),
        action="session.read",
        status="succeeded",
        status_code=200,
        result_metadata={"source": "test"},
        created_at=created_at,
    )
    assert first.delivery_audit.append(audit) == audit
    assert first.delivery_audit.list_for_session(audit.session_id) == [audit]
    assert second.delivery_audit.list_for_session(audit.session_id) == []
