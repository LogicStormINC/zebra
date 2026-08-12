from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.effect_dispatch import EffectScheduleRequest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id, new_tool_call_id
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage import (
    PostgresEffectDispatchStore,
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


def test_effect_state_reads_terminal_and_unresolved_dispatches(postgres_dsn: str) -> None:
    namespace = f"effect-state-{uuid4()}"
    session_id = new_session_id()
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    lease = PostgresLeaseStore(postgres_dsn, deployment_namespace=namespace).acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )
    store = PostgresEffectDispatchStore(postgres_dsn, deployment_namespace=namespace)
    request = EffectScheduleRequest(
        root_session_id=session_id,
        identity=EffectIdentity(
            authority_scope_hash="authority",
            tool_name="publish",
            operation_kind="create",
            target_hash="target",
            canonical_effect_hash="effect",
            external_operation_id_hash="provider-operation",
        ),
        request_hash="a" * 64,
        payload_artifact_ref="artifact://effect/request.json",
        started_event=SessionEvent(
            event_id=new_event_id(),
            session_id=session_id,
            sequence=0,
            event_type=EventType.TOOL_EXECUTION_STARTED,
            payload={},
            actor=EventActor.TOOL,
            created_at=datetime.now(UTC),
        ),
    )
    dispatch = store.schedule(request, fence=lease.fence)

    assert store.terminal_keys(session_id) == frozenset()
    assert store.has_uncertain(session_id) is True

    claim = store.claim_next(session_id, fence=lease.fence, claim_ttl=timedelta(seconds=30))
    assert claim is not None
    store.complete(
        claim,
        result=ToolResult(
            tool_call_id=new_tool_call_id(),
            status=ToolCallStatus.EXECUTED,
            output="created",
            metadata={"provider_operation_id_hash": "provider-operation"},
        ),
        terminal_event=SessionEvent(
            event_id=new_event_id(),
            session_id=session_id,
            sequence=1,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            payload={},
            actor=EventActor.TOOL,
            created_at=datetime.now(UTC),
        ),
    )

    assert store.terminal_keys(session_id) == frozenset({dispatch.ledger_key})
    assert store.has_uncertain(session_id) is False
