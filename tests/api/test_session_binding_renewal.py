from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.task_bindings import host_context_digest
from zebra_agent_api.session_binding import (
    _build_binding_snapshot,
    renew_task_binding_snapshot,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _context(
    *,
    grant_id: str,
    workspace_ref: str = "trench-workspace:user-1",
    expires_at: datetime | None = None,
) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=grant_id,
        host_app_id="trench",
        namespace_id="trench:user-1",
        workspace_ref=workspace_ref,
        resource_refs=(HostResourceRef(type="trench.source", id="source-1"),),
        scopes=("trench:source:read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=10_000,
            max_artifact_bytes=1_000_000,
        ),
        origin="https://trench.local",
        policy_version="trench-read-v1",
        expires_at=expires_at or NOW + timedelta(minutes=5),
    )


def test_renewal_appends_revision_and_preserves_frozen_anchors() -> None:
    original = _context(grant_id="grant-1")
    binding = _build_binding_snapshot(
        "11111111-1111-1111-1111-111111111111",
        host_context=original,
        definition_snapshot_digest="a" * 64,
        frozen_manifest_digest="b" * 64,
    )
    fresh = _context(grant_id="grant-2", expires_at=NOW + timedelta(minutes=10))

    renewed = renew_task_binding_snapshot(binding, fresh, bound_at=NOW)

    assert renewed.binding_revision == 2
    assert renewed.host_capability.host_context == fresh
    assert renewed.host_capability.grant_digest == host_context_digest(fresh)
    assert renewed.host_capability.grant_expires_at == fresh.expires_at
    assert renewed.agent_capability_ceiling == binding.agent_capability_ceiling
    assert renewed.host_capability.manifest_digest == binding.host_capability.manifest_digest
    assert renewed.host_capability.connector_profile_digest == (
        binding.host_capability.connector_profile_digest
    )
    assert renewed.zebra_policy_digest == binding.zebra_policy_digest


def test_renewal_rejects_workspace_drift() -> None:
    binding = _build_binding_snapshot(
        "11111111-1111-1111-1111-111111111111",
        host_context=_context(grant_id="grant-1"),
        definition_snapshot_digest="a" * 64,
    )

    with pytest.raises(ValueError, match="workspace drifted"):
        renew_task_binding_snapshot(
            binding,
            _context(grant_id="grant-2", workspace_ref="trench-workspace:user-2"),
        )


def test_host_context_digest_covers_ephemeral_authority_fields() -> None:
    first = _context(grant_id="grant-1")
    second = _context(grant_id="grant-2")

    assert host_context_digest(first) != host_context_digest(second)
