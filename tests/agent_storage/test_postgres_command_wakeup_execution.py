"""Real PG handoff-to-worker; deterministic model and temporary local runtime only."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import (
    SQLiteEffectLedger,
    SQLiteProviderContinuationStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres_composition import postgres_control_plane_stores
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)
from zebra_agent_worker.continuation_lifecycle import start_recovered_continuation
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.runtime_authority import TrustedLocalExecutionAuthorityResolver
from zebra_agent_worker.tool_run_index import ToolRunIndexer

from tests.agent_storage.test_command_wakeup import _binding, _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff
from tests.agent_storage.test_postgres_command_wakeup_receipts import _receipt
from tests.agent_storage.test_postgres_leases import _expire
from tests.worker.execution.worker_execution_support import _assistant_only_gateway, _settings

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _authority(scope):
    return TrustedLocalExecutionAuthorityResolver(
        authority_issuer=scope.authority_issuer, namespace_id=scope.namespace_id,
        policy_ref="policy/local@1", policy_version="test-v1", policy_effective_digest="a" * 64,
    )


def test_fixture_authority_resolves_valid_snapshot_without_database():
    scope = OpaqueAuthorityScope(authority_issuer="https://trench.example", namespace_id="tenant-a")
    request = ExecutionAuthorityResolutionRequest(
        session_id=uuid4(), attempt_number=1, scope=scope, validated_at=datetime.now(UTC),
    )
    snapshot = _authority(scope).resolve_for_attempt(request)
    assert snapshot.policy_ref == "policy/local@1"
    assert snapshot.snapshot_digest


def _setup(
    dsn, tmp_path, monkeypatch, *, interaction_mode=None, skill_components=(),
    manifest_digest="d" * 64,
):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="claimed execution",
            user_input="Return a short answer.",
            workspace_root=tmp_path,
            interaction_mode=interaction_mode,
            skill_components=skill_components,
            host_context=_binding("fixture").host_capability.host_context,
        )
    )
    binding = _binding(str(bootstrap.session.session_id))
    binding = binding.model_copy(update={"host_capability": binding.host_capability.model_copy(
        update={"manifest_digest": manifest_digest},
    )})
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=binding,
        )
    )
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    _enable(dsn)
    command = _command(bootstrap.session.session_id)
    _store(dsn).append(command)
    lease = _handoff(dsn, command).lease
    assert lease is not None
    scope = OpaqueAuthorityScope(authority_issuer="https://trench.example", namespace_id="tenant-a")
    stores = postgres_control_plane_stores(
        dsn,
        deployment_namespace=NAMESPACE,
        memory_cursor_signing_key=b"x" * 32,
        artifact_objects=Mock(),
        history_scope=scope,
        continuation_scope=scope,
    )
    recovery = SessionRecoveryService(
        stores.events,
        stores.sessions,
        stores.workspaces,
        worker_projection_transaction=stores.workspaces,
        deployment_namespace=NAMESPACE,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs),
    )
    claims = SessionClaimService(stores.leases, recovery)
    service = SessionExecutionService(
        database_path=tmp_path / "unused.db",
        claim_service=claims,
        resume_service=SessionResumeService(claims),
        settings=_settings(tmp_path / "unused.db"),
        stores=stores,
        worker_projection_transaction=stores.workspaces,
        deployment_namespace=NAMESPACE,
        execution_authority_scope=scope,
        execution_authority_resolver=_authority(scope),
    )
    # This storage-to-worker check uses an explicit temporary local runtime,
    # not cloud service composition. Keep its auxiliary stores real and isolated;
    # all Events, projections, leases and command receipts remain PostgreSQL.
    service._provider_continuation_store = SQLiteProviderContinuationStore(
        tmp_path / "provider-continuations.db"
    )
    service._effect_ledger = SQLiteEffectLedger(tmp_path / "effects.db")
    monkeypatch.setattr(
        claims,
        "acquire_lease",
        Mock(
            side_effect=AssertionError("must not acquire twice"),
        ),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    return service, stores, lease


def test_actual_handoff_worker_result_and_exact_receipt(dsn, tmp_path, monkeypatch):
    service, stores, lease = _setup(dsn, tmp_path, monkeypatch)
    result = service.execute_claimed_session(lease)
    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Worker completed the session."
    receipt = _receipt(dsn)
    assert receipt["control_plane_epoch"] == lease.fence.control_plane_epoch
    assert receipt["fencing_token"] == lease.fence.fencing_token
    assert receipt["owner_instance_id"] == lease.fence.owner_instance_id
    events = {event.event_id: event for event in stores.events.list_for_session(lease.session_id)}
    assert events[receipt["started_event_id"]].event_type is EventType.HARNESS_ATTEMPT_STARTED
    handled = events[receipt["handled_event_id"]]
    assert handled.event_type is EventType.TURN_COMPLETED
    assert receipt["turn_id"] == handled.payload["turn_id"]
    completed = [event for event in events.values()
                 if event.event_type is EventType.SESSION_COMPLETED]
    assert len(completed) == 1 and completed[0].sequence > handled.sequence
    assert _receipt(dsn)["handled_event_id"] == handled.event_id
    assert stores.leases.get(lease.session_id) is None
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT status FROM session_command_pending").fetchone() == (
            "done",
        )


@pytest.mark.parametrize("successor", [False, True])
def test_expired_or_successor_handoff_never_executes(dsn, tmp_path, monkeypatch, successor):
    service, stores, lease = _setup(dsn, tmp_path, monkeypatch)
    _expire(dsn, NAMESPACE, lease.session_id)
    current = (
        stores.leases.acquire(
            lease.session_id, owner_instance_id="successor", ttl=timedelta(seconds=30)
        )
        if successor
        else None
    )
    execute = Mock(side_effect=AssertionError("lost fence must not execute"))
    monkeypatch.setattr(service, "_execute_claimed_session_once", execute)
    with pytest.raises(LeaseLostError):
        service.execute_claimed_session(lease)
    execute.assert_not_called()
    if current is not None:
        assert stores.leases.get(lease.session_id).fence == current.fence
    assert _receipt(dsn)["started_event_id"] is None


@pytest.mark.parametrize("reject_receipt", [False, True])
def test_completed_output_start_recorder_is_atomic(dsn, tmp_path, monkeypatch, reject_receipt):
    service, stores, lease = _setup(dsn, tmp_path, monkeypatch)
    claimed = service._claim_service.recover_lease(lease, lease_ttl_seconds=30)
    recorder = service._projection_recorder_factory.build(
        session=claimed.recovery.session,
        workspace=claimed.recovery.workspace,
        lease=claimed.lease,
        ownership_check=lambda: None,
    )
    before = stores.events.list_for_session(lease.session_id)
    if reject_receipt:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "ALTER TABLE command_handoff_receipts ADD CONSTRAINT reject_start "
                "CHECK(started_event_id IS NULL)"
            )
    continuation = SimpleNamespace(
        completed_output="durable output",
        tool_call=SimpleNamespace(name="files.read", tool_call_id="test-call"),
    )

    def start():
        return start_recovered_continuation(
            claimed,
            continuation=continuation,
            clarification=None,
            event_store=stores.events,
            recovery_service=service._recovery_service,
            started_at=lease.heartbeat_at,
            recorder=recorder,
        )

    if reject_receipt:
        with pytest.raises(psycopg.errors.CheckViolation):
            start()
        assert stores.events.list_for_session(lease.session_id) == before
        assert _receipt(dsn)["started_event_id"] is None
        assert stores.sessions.get_session(lease.session_id).current_sequence == before[-1].sequence
    else:
        start()
        event = stores.events.list_for_session(lease.session_id)[-1]
        assert event.payload["completed_continuation"] is True
        assert _receipt(dsn)["started_event_id"] == event.event_id
