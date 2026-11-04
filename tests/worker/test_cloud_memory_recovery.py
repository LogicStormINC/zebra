"""Budget-governed Tasks never pay for an unaccounted recovery title."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from agent_core.domain.sessions import SessionStatus
from zebra_agent_worker.cloud_memory_recovery import CloudMemoryFinalizationRecovery


def test_guarded_task_keeps_memory_finalization_without_title_or_retry_charge(monkeypatch):
    sid = uuid4()
    calls = []
    session = SimpleNamespace(session_id=sid, status=SessionStatus.COMPLETED)
    workspace = SimpleNamespace(definition_snapshot=None)
    recorder = SimpleNamespace(
        session=session, workspace=workspace, worker_mutation_authority=object()
    )
    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=session, workspace=workspace), lease=object()
    )
    monkeypatch.setattr(
        "zebra_agent_worker.cloud_memory_recovery.LeaseHeartbeat",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(require_owned=lambda: None)),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.cloud_memory_recovery.finalize_cloud_memory",
        lambda **kwargs: calls.append("memory") or True,
    )
    monkeypatch.setattr(
        "zebra_agent_worker.cloud_memory_recovery.memory_completion_revision", lambda *args: 1
    )
    monkeypatch.setattr(
        "zebra_agent_worker.cloud_memory_recovery._mark_memory_recovered",
        lambda *args: calls.append("marked"),
    )
    recovery = CloudMemoryFinalizationRecovery(
        claim_service=SimpleNamespace(claim_session=lambda *args, **kwargs: claimed),
        recorder_factory=SimpleNamespace(build=lambda **kwargs: recorder),
        memory_store=object(),
        idempotency_store=SimpleNamespace(
            get=lambda **kwargs: (_ for _ in ()).throw(AssertionError("title quota was consumed"))
        ),
        deployment_namespace="fixture",
        event_store=SimpleNamespace(list_for_session=lambda _: []),
        projection_store=object(),
        workspace_store=object(),
        title_service_factory=lambda: (_ for _ in ()).throw(
            AssertionError("paid title constructed")
        ),
        paid_title_allowed=lambda current: current != sid,
    )
    assert recovery.recover(
        sid, worker_id="fixture", recovered_at=datetime.now(UTC), lease_ttl_seconds=30
    )
    assert calls == ["memory", "marked"]
    assert recovery._title_attempts == {}


def test_worker_paces_empty_memory_recovery_without_delaying_progress(monkeypatch):
    from zebra_agent_worker import worker_loop_service

    clock = [0.0]
    polls = []
    pending = []
    monkeypatch.setattr(worker_loop_service, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    service = worker_loop_service.WorkerLoopService(
        projection_store=SimpleNamespace(
            list_memory_recovery_sessions=lambda **kwargs: polls.append(clock[0]) or pending
        ),
        execution_service=object(),
        cloud_memory_recovery=SimpleNamespace(recover=lambda *args, **kwargs: True),
    )

    def tick():
        service.maintenance_once(worker_id="fixture", batch_size=16, lease_ttl_seconds=30)
        service._cloud_memory_recovery_thread.join(timeout=1)
        assert not service._cloud_memory_recovery_thread.is_alive()

    tick()
    clock[0] = 0.25
    tick()
    assert polls == [0.0]

    pending.append(SimpleNamespace(session_id=uuid4(), status=SessionStatus.COMPLETED))
    clock[0] = 1.0
    tick()
    clock[0] = 1.25
    tick()
    assert polls == [0.0, 1.0, 1.25]
