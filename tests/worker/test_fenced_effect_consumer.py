from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_storage import (
    PostgresEffectDispatchStore,
    PostgresLeaseStore,
    SQLiteArtifactPayloadStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_tools import FencedEffectToolGateway
from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat, LeaseHeartbeatError


class _ClaimService:
    def __init__(self, *, heartbeat_error: BaseException | None = None) -> None:
        self.heartbeat_error = heartbeat_error
        self.heartbeated = Event()
        self.released = Event()

    def heartbeat_lease(
        self,
        lease: WorkerLease,
        *,
        lease_ttl_seconds: int,
        checkpoint: int | None = None,
    ) -> WorkerLease:
        del lease_ttl_seconds, checkpoint
        self.heartbeated.set()
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return lease.model_copy(
            update={
                "heartbeat_at": lease.heartbeat_at + timedelta(milliseconds=100),
                "expires_at": lease.expires_at + timedelta(seconds=1),
            }
        )

    def release_lease(self, lease: WorkerLease) -> None:
        del lease
        self.released.set()


def test_background_heartbeat_runs_and_release_follows_join() -> None:
    service = _ClaimService()

    with LeaseHeartbeat(
        cast(SessionClaimService, service),
        _lease(),
        lease_ttl_seconds=1,
    ) as heartbeat:
        assert service.heartbeated.wait(1)
        heartbeat.require_owned()

    assert service.released.is_set()


def test_background_heartbeat_loss_stops_new_owned_work() -> None:
    service = _ClaimService(heartbeat_error=LeaseLostError("stale fence"))

    with pytest.raises(LeaseHeartbeatError, match="ownership was lost"):
        with LeaseHeartbeat(
            cast(SessionClaimService, service),
            _lease(),
            lease_ttl_seconds=1,
        ) as heartbeat:
            assert service.heartbeated.wait(1)
            heartbeat.require_owned()

    assert service.released.is_set()


def test_real_postgres_consumer_replays_terminal_result_without_provider_call(
    tmp_path,
) -> None:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    namespace = f"consumer-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    session_id = new_session_id()
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )
    gateway = _Gateway()
    accepted: list[SessionEvent] = []

    def next_event(event_type, actor, payload):
        return SessionEvent.create(
            session_id=session_id,
            sequence=len(accepted),
            event_type=event_type,
            actor=actor,
            payload=payload,
        )

    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=PostgresEffectDispatchStore(dsn, deployment_namespace=namespace),
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "consumer.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=lease.fence,
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=next_event,
        accept_event=accepted.append,
        ownership_check=lambda: None,
    )
    try:
        first = guarded.execute(_tool_call())
        replay = guarded.execute(_tool_call())
        assert replay.output == first.output == "ok"
        assert gateway.calls == 1
    finally:
        _delete_namespace(dsn, namespace)


def _lease() -> WorkerLease:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    return WorkerLease(
        session_id=new_session_id(),
        fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=1,
            owner_instance_id="worker-a",
        ),
        checkpoint=3,
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=1),
    )


class _Gateway:
    model_tools = ()
    effective_mcp_tools = ()
    effective_skill_components = ()
    parallel_safe_tools = frozenset()
    parallel_batch_limits = {}

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
        )

    def resolve_model_tool_calls(self, tool_calls):
        return tool_calls

    def close(self) -> None:
        pass


def _tool_call() -> ToolCall:
    from agent_core.domain.identifiers import new_tool_call_id

    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": "deploy"},
        created_at=datetime.now(UTC),
    )


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
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )
