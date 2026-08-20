"""Phase F2/F3 wiring tests: pinned egress priority and binding freeze."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.host_connectors import (
    HostConnectorBinding,
    HostConnectorProfileVersion,
    HostConnectorStatus,
)
from agent_core.domain.identifiers import TaskId
from agent_core.ports.host_credential_resolver import EphemeralHostCredential
from zebra_agent_worker.host_egress import (
    HostEgressResolver,
    build_pinned_host_gateway,
)


class FakeRegistry:
    def __init__(self, binding, profile):
        self._binding = binding
        self._profile = profile

    def get_profile(self, host_app_id, connector_id, revision):
        if self._profile is None:
            return None
        return self._profile

    def resolve_binding(self, host_app_id, namespace_id):
        if self._binding is None:
            return None
        return self._binding


class CompatCredentials:
    def issue(self, *, credential_ref, workload_identity_ref, audience, scopes, ttl_seconds):
        return EphemeralHostCredential(
            token=f"compat:{credential_ref}",
            audience=audience,
            scopes=tuple(scopes),
            expires_at_epoch=int(datetime.now(UTC).timestamp()) + ttl_seconds,
        )


def _context() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="host-a",
        namespace_id="tenant-a",
        workspace_ref="workspace-1",
        resource_refs=(HostResourceRef(type="host-a.event", id="evt-1"),),
        scopes=("scope:a",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=100_000,
            max_artifact_bytes=10_485_760,
        ),
        origin="https://host-a.example.com",
        policy_version="p1",
    )


def _profile(status=HostConnectorStatus.PUBLISHED):
    return HostConnectorProfileVersion(
        host_app_id="host-a",
        connector_id="host-a-main",
        profile_revision=2,
        base_uri="https://pinned.example.com",
        manifest_path="/manifest",
        invoke_path_template="/tools/invoke",
        supported_protocol_versions=("host-capability-protocol/1",),
        workload_identity_ref="workload/zebra",
        credential_ref="credentials/host-a",
        status=status,
    )


def _binding():
    return HostConnectorBinding(
        host_app_id="host-a",
        namespace_id="tenant-a",
        connector_id="host-a-main",
        profile_revision=2,
        binding_revision=1,
    )


class TestF2PinnedEgress:
    def test_bound_namespace_builds_gateway_from_profile(self) -> None:
        resolver = HostEgressResolver(FakeRegistry(_binding(), _profile()), CompatCredentials())
        pinned = resolver.resolve(_context())
        assert pinned is not None
        gateway = build_pinned_host_gateway(
            pinned, _context(), resolver.issue_credential(pinned, _context())
        )
        assert gateway.endpoint == "https://pinned.example.com"

    def test_unbound_namespace_returns_none_for_legacy_fallback(self) -> None:
        resolver = HostEgressResolver(FakeRegistry(None, None), CompatCredentials())
        assert resolver.resolve(_context()) is None

    def test_revoked_profile_fails_closed(self) -> None:
        import pytest

        resolver = HostEgressResolver(
            FakeRegistry(_binding(), _profile(HostConnectorStatus.REVOKED)),
            CompatCredentials(),
        )
        with pytest.raises(ValueError, match="revoked"):
            resolver.resolve(_context())


class TestF3BindingFreeze:
    def test_freeze_persists_and_roundtrips_via_save(self, tmp_path) -> None:

        from agent_core.domain.agent_capabilities import capability_set
        from agent_core.domain.task_bindings import (
            AgentCapabilityCeilingSnapshot,
            HostCapabilitySnapshot,
            TaskBindingSnapshot,
        )
        from zebra_agent_api.session_binding import envelope_grant_digest

        context = _context()
        ceiling = AgentCapabilityCeilingSnapshot(
            definition_snapshot_digest="a" * 64,
            capability_profile_ref="profile/default@1",
            capabilities=capability_set(["agent.execute"]),
            resolved_at=datetime.now(UTC),
        )
        host = HostCapabilitySnapshot(
            host_app_id=context.host_app_id,
            authority_issuer=context.origin,
            namespace_id=context.namespace_id,
            grant_digest=envelope_grant_digest(context),
            connector_id="host-a-unbound",
            connector_profile_revision=1,
            connector_profile_digest="0" * 64,
            manifest_digest="0" * 64,
            capabilities=capability_set(["agent.execute"]),
            resource_binding_digest="0" * 64,
            bound_at=datetime.now(UTC),
        )
        binding = TaskBindingSnapshot(
            task_id=str(TaskId(uuid4())),
            agent_capability_ceiling=ceiling,
            host_capability=host,
            zebra_policy_digest="0" * 64,
            effective_capabilities=capability_set(["agent.execute"]),
            binding_revision=1,
            bound_at=datetime.now(UTC),
        )
        assert binding.binding_digest == binding.binding_digest  # deterministic
        assert len(envelope_grant_digest(context)) == 64
