"""Real PostgreSQL coverage for the durable session tenant namespace (v23)."""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import (
    PostgresEventStore,
    PostgresProjectionStore,
    apply_postgres_migrations,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_api.tenant_guard import (
    session_in_tenant,
    session_tenant_denied,
)

CREATED = datetime(2026, 8, 16, 15, 0, tzinfo=UTC)


def _host_context(namespace_id: str) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=f"grant-{namespace_id}",
        host_app_id=f"host-{namespace_id}",
        namespace_id=namespace_id,
        workspace_ref="workspace://unit",
        resource_refs=(HostResourceRef(type="trench.event", id="evt-1"),),
        scopes=("session.write",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=3600,
            max_model_tokens=100_000,
            max_artifact_bytes=1_000_000,
        ),
        origin="https://issuer.example",
        policy_version="policies/host/policy@v1",
    )


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"session_tenant_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_session_tenant_namespace_roundtrip_and_guard(dsn: str) -> None:
    store = PostgresProjectionStore(dsn, deployment_namespace="tenant-e2e")
    session_id = new_session_id()
    PostgresEventStore(dsn, deployment_namespace="tenant-e2e").append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "tenant probe"},
            created_at=CREATED,
        )
    )
    bound = Session(
        session_id=session_id,
        title="tenant probe",
        status=SessionStatus.READY,
        created_at=CREATED,
        updated_at=CREATED,
        current_sequence=0,
        namespace_id="tenant-a",
    )
    store.save_session(bound)
    fetched = store.get_session(session_id)
    assert fetched is not None
    assert fetched.namespace_id == "tenant-a"

    assert session_tenant_denied(store, str(session_id), _host_context("tenant-a")) is False
    assert session_tenant_denied(store, str(session_id), _host_context("tenant-b")) is True
    assert session_tenant_denied(store, str(session_id), None) is False
    assert session_in_tenant(fetched, _host_context("tenant-a")) is True
    assert session_in_tenant(fetched, _host_context("tenant-b")) is False

    unbound_id = new_session_id()
    PostgresEventStore(dsn, deployment_namespace="tenant-e2e").append(
        SessionEvent.create(
            session_id=unbound_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "internal probe"},
            created_at=CREATED,
        )
    )
    unbound = Session(
        session_id=unbound_id,
        title="internal probe",
        status=SessionStatus.READY,
        created_at=CREATED,
        updated_at=CREATED,
        current_sequence=0,
    )
    store.save_session(unbound)
    assert session_tenant_denied(store, str(unbound_id), _host_context("tenant-b")) is False
    assert session_in_tenant(unbound, _host_context("tenant-b")) is True
