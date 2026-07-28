from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.effect_dispatch import EffectEvidence, EffectScheduleRequest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    SessionId,
    new_event_id,
    new_session_id,
    new_tool_call_id,
)
from agent_core.domain.leases import WorkerLease
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage import (
    PostgresEffectDispatchStore,
    PostgresEventStore,
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from psycopg import sql


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def fault_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"effect-fault-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_schedule_outbox_failure_rolls_back_started_event(
    postgres_dsn: str,
    fault_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _lease(postgres_dsn, fault_namespace, session_id)
    store = _store(postgres_dsn, fault_namespace)
    with _effect_fault(postgres_dsn, fault_namespace, operation="INSERT", status="pending"):
        with pytest.raises(psycopg.errors.RaiseException, match="injected effect fault"):
            store.schedule(_request(session_id, sequence=0), fence=lease.fence)

    assert _events(postgres_dsn, fault_namespace, session_id) == []
    assert _outbox_count(postgres_dsn, fault_namespace) == 0


def test_terminal_outbox_failure_rolls_back_terminal_event(
    postgres_dsn: str,
    fault_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _lease(postgres_dsn, fault_namespace, session_id)
    store = _store(postgres_dsn, fault_namespace)
    request = _request(session_id, sequence=0)
    store.schedule(request, fence=lease.fence)
    claim = store.claim_next(session_id, fence=lease.fence, claim_ttl=timedelta(seconds=30))
    assert claim is not None
    with _effect_fault(postgres_dsn, fault_namespace, operation="UPDATE", status="succeeded"):
        with pytest.raises(psycopg.errors.RaiseException, match="injected effect fault"):
            store.complete(
                claim,
                result=ToolResult(
                    tool_call_id=new_tool_call_id(),
                    status=ToolCallStatus.EXECUTED,
                    output="created",
                ),
                terminal_event=_event(
                    session_id, sequence=1, event_type=EventType.TOOL_EXECUTION_COMPLETED
                ),
            )

    assert _events(postgres_dsn, fault_namespace, session_id) == [request.started_event]
    assert _outbox_status(postgres_dsn, fault_namespace) == "claimed"


def test_retry_outbox_failure_rolls_back_retry_started_event(
    postgres_dsn: str,
    fault_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _lease(postgres_dsn, fault_namespace, session_id)
    store = _store(postgres_dsn, fault_namespace)
    request = _request(session_id, sequence=0)
    first = store.schedule(request, fence=lease.fence)
    claim = store.claim_next(session_id, fence=lease.fence, claim_ttl=timedelta(seconds=30))
    assert claim is not None
    failed = _event(session_id, sequence=1, event_type=EventType.TOOL_EXECUTION_FAILED)
    store.fail_no_effect(
        claim,
        evidence=EffectEvidence(reason_code="provider_rejected"),
        terminal_event=failed,
    )
    with _effect_fault(postgres_dsn, fault_namespace, operation="INSERT", status="pending"):
        with pytest.raises(psycopg.errors.RaiseException, match="injected effect fault"):
            store.retry_failed_no_effect(
                first.dispatch_id,
                current_fence=lease.fence,
                retry_key="retry-fault",
                started_event=_event(
                    session_id, sequence=2, event_type=EventType.TOOL_EXECUTION_STARTED
                ),
            )

    assert _events(postgres_dsn, fault_namespace, session_id) == [
        request.started_event,
        failed,
    ]
    assert _outbox_count(postgres_dsn, fault_namespace) == 1


@contextmanager
def _effect_fault(
    dsn: str,
    namespace: str,
    *,
    operation: str,
    status: str,
) -> Iterator[None]:
    suffix = uuid4().hex
    function_name = sql.Identifier(f"inject_effect_fault_{suffix}")
    trigger_name = sql.Identifier(f"effect_fault_{suffix}")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.deployment_namespace = {} AND NEW.status = {} THEN
                        RAISE EXCEPTION 'injected effect fault';
                    END IF;
                    RETURN NEW;
                END
                $$
                """
            ).format(function_name, sql.Literal(namespace), sql.Literal(status))
        )
        connection.execute(
            sql.SQL("CREATE TRIGGER {} BEFORE {} ON effect_outbox ").format(
                trigger_name, sql.SQL(operation)
            )
            + sql.SQL("FOR EACH ROW EXECUTE FUNCTION {}()").format(function_name)
        )
    try:
        yield
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP TRIGGER {} ON effect_outbox").format(trigger_name))
            connection.execute(sql.SQL("DROP FUNCTION {}()").format(function_name))


def _store(dsn: str, namespace: str) -> PostgresEffectDispatchStore:
    return PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)


def _lease(dsn: str, namespace: str, session_id: SessionId) -> WorkerLease:
    return PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id, owner_instance_id="worker-fault", ttl=timedelta(minutes=1)
    )


def _request(session_id: SessionId, *, sequence: int) -> EffectScheduleRequest:
    return EffectScheduleRequest(
        root_session_id=session_id,
        identity=EffectIdentity(
            authority_scope_hash="authority",
            tool_name="publish",
            operation_kind="create",
            target_hash="target",
            canonical_effect_hash="effect",
        ),
        request_hash="a" * 64,
        payload_artifact_ref="artifact://effect/request.json",
        started_event=_event(
            session_id, sequence=sequence, event_type=EventType.TOOL_EXECUTION_STARTED
        ),
    )


def _event(session_id: SessionId, *, sequence: int, event_type: EventType) -> SessionEvent:
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload={},
        actor=EventActor.TOOL,
        created_at=datetime.now(UTC),
        idempotency_key=f"{event_type.value}-{sequence}-{uuid4()}",
    )


def _events(dsn: str, namespace: str, session_id: SessionId) -> list[SessionEvent]:
    return PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id)


def _outbox_count(dsn: str, namespace: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT count(*) FROM effect_outbox WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _outbox_status(dsn: str, namespace: str) -> str:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT status FROM effect_outbox WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchone()
    assert row is not None
    return cast(str, row[0])


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in (
            "effect_outbox",
            "session_events",
            "session_streams",
            "worker_leases",
            "control_plane_epochs",
        ):
            connection.execute(
                sql.SQL("DELETE FROM {} WHERE deployment_namespace = %s").format(
                    sql.Identifier(table)
                ),
                (namespace,),
            )
