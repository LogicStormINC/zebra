from datetime import UTC, datetime

from agent_core.application import governed_memory_scope
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.memories import MemoryVisibility


def _host_context(*principals: str) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="trench",
        namespace_id="tenant-a",
        workspace_ref="workspace-a",
        resource_refs=tuple(
            HostResourceRef(type="principal", id=principal) for principal in principals
        ),
        scopes=("agent.run",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=100_000,
            max_artifact_bytes=10_000_000,
        ),
        origin="https://trench.example.test",
        policy_version="v1",
        expires_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


def test_host_memory_scope_is_stable_and_principal_bound() -> None:
    scope = governed_memory_scope(
        fallback_repo_id="/ephemeral/session/path",
        host_context=_host_context("user-7"),
    )

    assert scope is not None
    assert scope.repo_id == "workspace-a"
    assert scope.user_id == "user-7"
    assert scope.tenant_id == "tenant-a"
    assert scope.query().visibility is MemoryVisibility.USER


def test_host_memory_scope_fails_closed_for_ambiguous_principal() -> None:
    assert (
        governed_memory_scope(
            fallback_repo_id="/ephemeral/session/path",
            host_context=_host_context("user-7", "user-8"),
        )
        is None
    )
