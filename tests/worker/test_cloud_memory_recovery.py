"""Budget-governed Tasks never pay for an unaccounted recovery title."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
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
    monkeypatch.setattr(
        worker_loop_service, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
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


@pytest.mark.parametrize(("error", "ceiling"), [(False, 30), (True, 5)])
def test_cloud_memory_discovery_backoff_caps_and_resets(monkeypatch, error, ceiling):
    from zebra_agent_worker import worker_loop_service, worker_polling

    monkeypatch.setattr(worker_polling, "uniform", lambda low, high: high)
    clock, polls, pending = [0.0], [], []
    failing = [error]

    def read(**kwargs):
        polls.append(clock[0])
        if failing[0]:
            raise RuntimeError("fixture unavailable")
        return pending

    monkeypatch.setattr(
        worker_loop_service, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    service = worker_loop_service.WorkerLoopService(
        projection_store=SimpleNamespace(list_memory_recovery_sessions=read),
        execution_service=object(), cloud_polling=True,
        cloud_memory_recovery=SimpleNamespace(recover=lambda *args, **kwargs: True),
    )

    def tick():
        service._start_cloud_memory_recovery(
            worker_id="fixture", batch_size=16, lease_ttl_seconds=30
        )
        thread = service._cloud_memory_recovery_thread
        assert thread is not None
        thread.join(timeout=1)
        assert not thread.is_alive()

    waits = []
    for _ in range(12):
        tick()
        delay = service._cloud_memory_recovery_at - clock[0]
        waits.append(delay)
        assert 0.05 <= delay <= ceiling
        count = len(polls)
        clock[0] = service._cloud_memory_recovery_at - 0.01
        tick()
        assert len(polls) == count
        clock[0] = service._cloud_memory_recovery_at
    assert waits[-1] == ceiling
    assert waits[-1] > waits[0]

    failing[0] = False
    pending.append(SimpleNamespace(session_id=uuid4(), status=SessionStatus.COMPLETED))
    tick()
    count = len(polls)
    tick()  # A successful batch may drain the next batch immediately.
    assert len(polls) == count + 1
    pending.clear()
    tick()
    assert service._cloud_memory_recovery_at - clock[0] == 1
