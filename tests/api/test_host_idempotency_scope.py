from datetime import UTC, datetime, timedelta

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from zebra_agent_api.idempotency import scoped_idempotency_key


def _context(principal: str, workspace: str = "workspace-1") -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=f"grant-{principal}",
        host_app_id="trench",
        namespace_id="trench",
        workspace_ref=workspace,
        resource_refs=(HostResourceRef(type="principal", id=principal),),
        scopes=("agent.run",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=60,
            max_model_tokens=1000,
            max_artifact_bytes=1024,
        ),
        origin="https://trench.local",
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_host_idempotency_is_partitioned_by_principal_and_workspace() -> None:
    key = "trench-event-task"

    owner = scoped_idempotency_key(key, _context("user-a"))
    repeated = scoped_idempotency_key(key, _context("user-a"))
    other_user = scoped_idempotency_key(key, _context("user-b"))
    other_workspace = scoped_idempotency_key(key, _context("user-a", "workspace-2"))

    assert owner == repeated
    assert len({owner, other_user, other_workspace}) == 3
    assert scoped_idempotency_key(key, None) == key
