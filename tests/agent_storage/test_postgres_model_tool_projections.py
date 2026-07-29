from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.leases import LeaseLostError
from agent_core.ports import WorkerMutationAuthority
from agent_storage import (
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresModelToolProjectionConflictError,
    PostgresModelToolProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"model_tool_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_worker_index_is_fenced_idempotent_and_replayable(dsn: str) -> None:
    namespace = f"model-tool-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    session_id = new_session_id()
    created = _event(session_id, 0, EventType.SESSION_CREATED, {"title": "test"})
    model = _event(
        session_id,
        1,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"attempt_number": 1, "assistant_message": "answer", "tool_call_count": 0},
    )
    tool = _event(
        session_id,
        2,
        EventType.TOOL_EXECUTION_COMPLETED,
        {
            "attempt_number": 1,
            "tool_name": "files.read",
            "status": "executed",
            "output": "ok",
            "metadata": {},
        },
    )
    for event in (created, model, tool):
        events.append(event)
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id, owner_instance_id="worker-a", ttl=timedelta(minutes=1)
    )
    authority = WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=session_id,
        lease_fence=lease.fence,
        expected_stream_revision=tool.sequence,
    )
    store = PostgresModelToolProjectionStore(dsn, deployment_namespace=namespace)

    assert store.index_worker_event(model, authority=authority) is not None
    assert store.index_worker_event(tool, authority=authority) is not None
    assert store.index_worker_event(model, authority=authority) is not None
    assert store.replay_session(session_id) == 2

    conflicting = model.model_copy(update={"event_id": uuid4()})
    with pytest.raises(PostgresModelToolProjectionConflictError):
        store.index_worker_event(conflicting, authority=authority)
    stale = authority.model_copy(
        update={"lease_fence": lease.fence.model_copy(update={"fencing_token": 99})}
    )
    with pytest.raises(LeaseLostError):
        store.index_worker_event(tool, authority=stale)
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM model_call_projections").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM tool_run_projections").fetchone() == (1,)


def _event(
    session_id: SessionId, sequence: int, event_type: EventType, payload: dict[str, object]
) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        actor=EventActor.HARNESS,
        payload=payload,
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
