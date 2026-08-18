"""Pinned Host egress tests: registry resolution and fail-closed lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
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
from agent_core.ports.host_credential_resolver import EphemeralHostCredential
from zebra_agent_worker.host_egress import (
    HostEgressResolver,
    PinnedHostConnector,
    build_pinned_host_gateway,
)


class FakeRegistry:
    def __init__(
        self,
        binding: HostConnectorBinding | None,
        profile: HostConnectorProfileVersion | None,
    ):
        self._binding = binding
        self._profile = profile

    def get_profile(self, host_app_id, connector_id, profile_revision):
        if self._profile is None:
            return None
        if (
            self._profile.host_app_id == host_app_id
            and self._profile.connector_id == connector_id
            and self._profile.profile_revision == profile_revision
        ):
            return self._profile
        return None

    def resolve_binding(self, host_app_id, namespace_id):
        if self._binding is None:
            return None
        if self._binding.host_app_id == host_app_id and self._binding.namespace_id == namespace_id:
            return self._binding
        return None


class FakeCredentialResolver:
    def __init__(self) -> None:
        self.issued: list[str] = []

    def issue(self, *, credential_ref, workload_identity_ref, audience, scopes, ttl_seconds):
        self.issued.append(credential_ref)
        return EphemeralHostCredential(
            token=f"ephemeral-{credential_ref}",
            audience=audience,
            scopes=tuple(scopes),
            expires_at_epoch=int(datetime.now(UTC).timestamp()) + ttl_seconds,
        )


def _profile(
    status: HostConnectorStatus = HostConnectorStatus.PUBLISHED,
) -> HostConnectorProfileVersion:
    return HostConnectorProfileVersion(
        host_app_id="host-a",
        connector_id="host-a-main",
        profile_revision=3,
        base_uri="https://pinned.example.com",
        manifest_path="/manifest",
        invoke_path_template="/tools/invoke",
        supported_protocol_versions=("host-capability-protocol/1",),
        workload_identity_ref="workload/zebra-worker",
        credential_ref="credentials/host-a",
        status=status,
    )


def _binding() -> HostConnectorBinding:
    return HostConnectorBinding(
        host_app_id="host-a",
        namespace_id="tenant-a",
        connector_id="host-a-main",
        profile_revision=3,
        binding_revision=2,
    )


def _context() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="host-a",
        namespace_id="tenant-a",
        workspace_ref="workspace-a",
        resource_refs=(HostResourceRef(type="host-a.event", id="evt-1"),),
        scopes=("scope:a",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=100_000,
            max_artifact_bytes=10_485_760,
        ),
        origin="https://host-a.example.com",
        policy_version="policy-v1",
    )


class TestResolve:
    def test_bound_namespace_pins_the_profile_revision(self) -> None:
        resolver = HostEgressResolver(
            FakeRegistry(_binding(), _profile()), FakeCredentialResolver()
        )
        pinned = resolver.resolve(_context())
        assert pinned is not None
        assert pinned.endpoint == "https://pinned.example.com"
        assert pinned.profile.profile_revision == 3
        assert pinned.binding_revision == 2
        assert not pinned.deprecated

    def test_unbound_namespace_returns_none_for_legacy_fallback(self) -> None:
        resolver = HostEgressResolver(FakeRegistry(None, None), FakeCredentialResolver())
        assert resolver.resolve(_context()) is None

    def test_missing_profile_revision_fails_closed(self) -> None:
        resolver = HostEgressResolver(FakeRegistry(_binding(), None), FakeCredentialResolver())
        with pytest.raises(ValueError, match="missing profile revision"):
            resolver.resolve(_context())

    def test_revoked_profile_fails_closed(self) -> None:
        resolver = HostEgressResolver(
            FakeRegistry(_binding(), _profile(HostConnectorStatus.REVOKED)),
            FakeCredentialResolver(),
        )
        with pytest.raises(ValueError, match="revoked"):
            resolver.resolve(_context())

    def test_deprecated_profile_still_serves_bound_tasks(self) -> None:
        resolver = HostEgressResolver(
            FakeRegistry(_binding(), _profile(HostConnectorStatus.DEPRECATED)),
            FakeCredentialResolver(),
        )
        pinned = resolver.resolve(_context())
        assert pinned is not None
        assert pinned.deprecated


class TestCredentialAndGateway:
    def test_credential_uses_profile_refs_and_never_persists(self) -> None:
        credentials = FakeCredentialResolver()
        resolver = HostEgressResolver(FakeRegistry(_binding(), _profile()), credentials)
        pinned = resolver.resolve(_context())
        assert pinned is not None
        credential = resolver.issue_credential(pinned, _context())
        assert credentials.issued == ["credentials/host-a"]
        assert credential.token == "ephemeral-credentials/host-a"
        assert credential.audience == "https://pinned.example.com"

    def test_gateway_is_built_from_the_pinned_profile(self) -> None:
        credentials = FakeCredentialResolver()
        resolver = HostEgressResolver(FakeRegistry(_binding(), _profile()), credentials)
        pinned = resolver.resolve(_context())
        assert pinned is not None
        gateway = build_pinned_host_gateway(
            pinned, _context(), resolver.issue_credential(pinned, _context())
        )
        assert gateway.endpoint == "https://pinned.example.com"
        assert gateway.workload_identity.subject == "workload/zebra-worker"
        assert gateway.workload_identity.namespace_id == "tenant-a"
        assert gateway.workload_identity.host_app_id == "host-a"

    def test_endpoint_follows_profile_not_global_settings(self) -> None:
        rotated = _profile().model_copy(
            update={"base_uri": "https://rotated.example.com", "profile_revision": 4}
        )
        pinned = PinnedHostConnector(profile=rotated, binding_revision=3)
        gateway = build_pinned_host_gateway(
            pinned,
            _context(),
            EphemeralHostCredential(
                token="tok",
                audience=rotated.base_uri,
                scopes=(),
                expires_at_epoch=2 ** 31,
            ),
        )
        assert gateway.endpoint == "https://rotated.example.com"
