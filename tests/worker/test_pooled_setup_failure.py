"""Real pooled binding reads, runtime binding and durable failure finalization."""

import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_storage import bootstrap_control_plane_epoch, postgres_control_plane_stores
from agent_storage.postgres.connection_pool import composition_pool, postgres_pool_scope
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
    load_session_task_binding,
)
from zebra_agent_worker import SessionClaimService, SessionExecutionService, SessionResumeService
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.execution_storage import compose_recovery
from zebra_agent_worker.runtime_setup import runtime_session_ids

from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_fixture
from tests.agent_storage.test_postgres_control_plane_composition import _ObjectReader
from tests.agent_storage.test_postgres_task_admission import _request
from tests.worker.execution.worker_execution_support import _settings

NS = "pooled-worker-setup"
dsn = _dsn_fixture
postgres_dsn = _postgres_fixture


def test_readonly_binding_does_not_crash_runtime_or_failure_finalization(
    dsn, tmp_path, monkeypatch,
):
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NS)
    scope = OpaqueAuthorityScope(authority_issuer="test", namespace_id="test")
    with postgres_pool_scope(dsn):
        pool = composition_pool(dsn)
        assert pool is not None
        pool.resize(1, 1)
        pool.wait()
        stores = postgres_control_plane_stores(
            dsn, deployment_namespace=NS, memory_cursor_signing_key=b"k" * 32,
            artifact_objects=_ObjectReader(), history_scope=scope, continuation_scope=scope,
        )
        _, _, recovery = compose_recovery(
            stores, stores.worker_projection_transaction, NS, stores.artifact_payloads,
        )
        claims = SessionClaimService(stores.leases, recovery)
        service = SessionExecutionService(
            database_path=tmp_path / "unused.sqlite", claim_service=claims,
            resume_service=SessionResumeService(claims), settings=_settings(tmp_path / "unused"),
            stores=stores, worker_projection_transaction=stores.worker_projection_transaction,
            deployment_namespace=NS,
        )
        bound = []

        def fail_after_binding(claimed, **kwargs):
            session = claimed.lease.session_id
            assert load_session_task_binding(
                dsn, deployment_namespace=NS, session_id=session,
            ) is None
            assert runtime_session_ids(stores.tasks, session) == (str(session),)
            bound.append(session)
            raise WorkerExecutionError("synthetic runtime setup failure")

        monkeypatch.setattr(service, "_execute_claimed_session_once", fail_after_binding)
        # A second invocation on the same service must still work after the
        # first failure is durably finalized, rather than requiring a process restart.
        for _ in range(2):
            request = _request()
            PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NS).admit(request)
            command = SessionCommand(
                session_id=request.session.session_id, kind=SessionCommandKind.RUN,
                expected_revision=request.session.current_sequence,
                idempotency_key=str(request.session.session_id),
                payload={"run_id": f"pool:{request.session.session_id}"},
            )
            stores.events.append(SessionEvent.create(
                session_id=command.session_id, sequence=command.expected_revision + 1,
                event_type=EventType.SESSION_COMMAND_ACCEPTED, actor=EventActor.USER,
                payload=command.event_payload(),
            ))
            result = service.execute_session(request.session.session_id, worker_id="pool-test")
            assert result.session.status is SessionStatus.FAILED
            assert any(event.event_type is EventType.SESSION_FAILED for event in result.events)
            assert stores.leases.get(request.session.session_id) is None
        assert len(bound) == 2
        assert not (tmp_path / "unused.sqlite").exists()


def test_pooled_read_reset_keeps_tenant_refusal_and_next_writer(dsn):
    from agent_storage import PostgresAgentTaskStore

    with postgres_pool_scope(dsn):
        pool = composition_pool(dsn)
        assert pool is not None
        pool.resize(1, 1)
        pool.wait()
        request = _request()
        PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NS).admit(request)
        with pytest.raises(ValueError, match="not found"):
            load_session_task_binding(
                dsn, deployment_namespace="foreign-tenant", session_id=request.session.session_id,
            )
        tasks = PostgresAgentTaskStore(dsn, deployment_namespace=NS)
        assert runtime_session_ids(tasks, request.session.session_id) == (
            str(request.session.session_id),
        )
        foreign = PostgresAgentTaskStore(dsn, deployment_namespace="foreign-tenant")
        assert foreign.get_task(request.session.session_id) is None
