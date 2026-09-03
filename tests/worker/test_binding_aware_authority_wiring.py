"""Phase F1: binding-aware Attempt authority in the execution service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from zebra_agent_worker.bound_execution_authority import (
    BoundHostExecutionAuthorityResolver,
)
from zebra_agent_worker.loop import _task_binding_id

SESSION = SessionId(uuid4())
ISSUER = "https://host-a.example.com"
NAMESPACE = "tenant-a"


def _binding() -> TaskBindingSnapshot:
    caps = capability_set(["agent.execute", "evidence.read"])
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/parent@1",
        capabilities=caps,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-a",
        authority_issuer=ISSUER,
        namespace_id=NAMESPACE,
        grant_digest="c" * 64,
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connector_id="host-a-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=caps,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(SESSION),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=caps,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def test_loader_result_drives_the_bound_resolver() -> None:
    binding = _binding()
    resolver = BoundHostExecutionAuthorityResolver(binding=binding)
    assert resolver.scope.namespace_id == NAMESPACE
    assert resolver.scope.authority_issuer == ISSUER


def test_execution_service_accepts_a_binding_loader(tmp_path) -> None:
    """The F1 seam exists and is optional (None keeps today's behavior)."""

    from zebra_agent_worker.execution import SessionExecutionService

    seen: list[SessionId] = []

    def loader(session_id: SessionId):
        seen.append(session_id)
        return _binding()

    service = SessionExecutionService(
        database_path=tmp_path / "sessions.sqlite",
        claim_service=None,  # type: ignore[arg-type]
        resume_service=None,  # type: ignore[arg-type]
        task_binding_loader=loader,
    )
    assert service is not None
    # the loader is only invoked during cloud execution with a claimed lease;
    # the seam's presence and optionality is the contract under test here
    assert seen == []


def test_internal_segment_loads_the_root_task_binding() -> None:
    root_task_id = TaskId(uuid4())
    internal_segment_id = SessionId(uuid4())
    tasks = SimpleNamespace(
        ensure_for_session=lambda session_id: SimpleNamespace(
            task_id=root_task_id,
            active_segment_id=session_id,
        )
    )

    assert _task_binding_id(tasks, internal_segment_id) == root_task_id
