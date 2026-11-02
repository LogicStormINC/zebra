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
