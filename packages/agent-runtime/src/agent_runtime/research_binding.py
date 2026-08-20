"""Parent binding construction for child delegation derivation."""

from __future__ import annotations

from agent_core.domain.task_bindings import TaskBindingSnapshot


def _make_parent_binding_for_derivation(
    parent_uuid: object, parent_binding_digest: str | None
) -> TaskBindingSnapshot:
    """Construct a minimal parent binding for child derivation.

    Uses the frozen digest when available; falls back to a read-only
    baseline. The child can only narrow below this ceiling.
    """

    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from agent_core.domain.agent_capabilities import capability_set as _caps
    from agent_core.domain.task_bindings import (
        AgentCapabilityCeilingSnapshot,
        HostCapabilitySnapshot,
    )

    caps = _caps(["agent.execute", "evidence.read"])
    digest = parent_binding_digest or "0" * 64
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest=digest,
        capability_profile_ref="profile/parent@1",
        capabilities=caps,
        resolved_at=_dt.now(_UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="derived-parent",
        authority_issuer="https://derived.local",
        namespace_id="derived",
        grant_digest=digest,
        connector_id="derived-unbound",
        connector_profile_revision=1,
        connector_profile_digest=digest,
        manifest_digest=digest,
        capabilities=caps,
        resource_binding_digest=digest,
        bound_at=_dt.now(_UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(parent_uuid),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest=digest,
        effective_capabilities=caps,
        binding_revision=1,
        bound_at=_dt.now(_UTC),
    )
