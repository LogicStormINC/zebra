"""An existing fenced lease enters the same worker lifecycle without acquisition."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import SessionStatus
from agent_storage import SQLiteLeaseStore
from zebra_agent_worker.continuation_lifecycle import start_recovered_continuation
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot

from tests.worker.execution.worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _created_at,
    _seed_ready_session,
)


def _setup(tmp_path, monkeypatch):
    path = tmp_path / "worker.db"
    session = _seed_ready_session(path, tmp_path)
    service = _build_execution_service(path)
    lease = service._claim_service.acquire_lease(
        session,
        worker_id="handoff-owner",
        claimed_at=_created_at(),
        lease_ttl_seconds=30,
    )
    monkeypatch.setattr(
        service._claim_service,
        "acquire_lease",
        Mock(
            side_effect=AssertionError("must not acquire a second lease"),
        ),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    return service, lease, SQLiteLeaseStore(path)


def test_claimed_execution_completes_with_the_same_fence(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    execute = service._execute_claimed_session_once
    seen = []

    def observed(claimed, **kwargs):
        seen.append(claimed.lease.fence)
        return execute(claimed, **kwargs)

    monkeypatch.setattr(service, "_execute_claimed_session_once", observed)
    result = service.execute_claimed_session(lease, executed_at=_created_at())
    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Worker completed the session."
    assert seen == [lease.fence]
    assert leases.get(lease.session_id) is None


def test_claimed_recovery_failure_releases_owned_lease(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service._claim_service, "recover_lease", Mock(side_effect=ValueError("setup"))
    )
    with pytest.raises(ValueError, match="setup"):
        service.execute_claimed_session(lease)
    assert leases.get(lease.session_id) is None


def test_claimed_stale_retry_keeps_the_exact_fence(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    execute = service._execute_claimed_session_once
    seen = []

    def once(claimed, **kwargs):
        seen.append(claimed.lease.fence)
        if len(seen) == 1:
            raise StaleExecutionSnapshot("concurrent event")
        return execute(claimed, **kwargs)

    monkeypatch.setattr(service, "_execute_claimed_session_once", once)
    assert service.execute_claimed_session(lease).session.status is SessionStatus.COMPLETED
    assert seen == [lease.fence, lease.fence]
    assert leases.get(lease.session_id) is None


def test_claimed_interruption_releases_owned_lease(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service, "_execute_claimed_session_once", Mock(side_effect=KeyboardInterrupt)
    )
    with pytest.raises(KeyboardInterrupt):
        service.execute_claimed_session(lease)
    assert leases.get(lease.session_id) is None


def test_claimed_resume_failure_releases_owned_lease(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service._resume_service, "require_resumable", Mock(side_effect=ValueError("not resumable"))
    )
    with pytest.raises(ValueError, match="not resumable"):
        service.execute_claimed_session(lease)
    assert leases.get(lease.session_id) is None


def test_claimed_setup_failure_uses_existing_finalization(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service,
        "_execute_claimed_session_once",
        Mock(side_effect=WorkerExecutionError("setup failed")),
    )
    result = service.execute_claimed_session(lease)
    assert result.session.status is SessionStatus.FAILED
    assert leases.get(lease.session_id) is None


def test_claimed_successor_fence_is_not_released(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    leases.release(lease.session_id, fence=lease.fence)
    from datetime import timedelta

    successor = leases.acquire(
        lease.session_id, owner_instance_id="successor", ttl=timedelta(seconds=30)
    )
    with pytest.raises(LeaseLostError):
        service.execute_claimed_session(lease)
    assert leases.get(lease.session_id).fence == successor.fence


def test_claimed_naive_time_rejected_and_lease_cleaned(tmp_path, monkeypatch):
    service, lease, leases = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="timezone-aware"):
        service.execute_claimed_session(lease, executed_at=datetime(2026, 1, 1))
    assert leases.get(lease.session_id) is None


def test_claimed_entry_requires_worker_lease(tmp_path, monkeypatch):
    service, _, _ = _setup(tmp_path, monkeypatch)
    with pytest.raises(TypeError, match="WorkerLease"):
        service.execute_claimed_session(SimpleNamespace())


@pytest.mark.parametrize("with_recorder", [True, False])
def test_completed_output_start_uses_supplied_recorder_only(tmp_path, monkeypatch, with_recorder):
    service, lease, _ = _setup(tmp_path, monkeypatch)
    claimed = service._claim_service.recover_lease(lease, lease_ttl_seconds=30)
    event_store = Mock()
    recorder = Mock() if with_recorder else None
    recovery = Mock()
    recovery.recover_session.return_value = claimed.recovery
    continuation = SimpleNamespace(
        completed_output="already durable",
        tool_call=SimpleNamespace(name="files.read", tool_call_id="1"),
    )
    result = start_recovered_continuation(
        claimed,
        continuation=continuation,
        clarification=None,
        event_store=event_store,
        recovery_service=recovery,
        started_at=_created_at(),
        recorder=recorder,
    )
    writer = recorder.append_event if with_recorder else event_store.append
    event = writer.call_args.args[0]
    assert event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    assert event.payload["completed_continuation"] is True
    assert result.lease.fence == lease.fence
    if with_recorder:
        event_store.append.assert_not_called()
