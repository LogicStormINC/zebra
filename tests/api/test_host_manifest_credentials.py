from types import SimpleNamespace

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from zebra_agent_api.host_manifest_freeze import HostManifestFreezeError, _discover_once


def test_manifest_discovery_without_configured_workload_credential_fails_closed() -> None:
    profile = SimpleNamespace(
        workload_identity_ref="workload/zebra",
        credential_ref="credentials/trench-hmac",
        base_uri="https://trench.example.com",
    )
    context = HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="trench",
        namespace_id="tenant-a",
        workspace_ref="workspace-a",
        resource_refs=(HostResourceRef(type="event", id="evt-1"),),
        scopes=("event.read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=30,
            max_model_tokens=1_000,
            max_artifact_bytes=1_000,
        ),
        origin="https://trench.example.com",
        policy_version="policy-v1",
    )

    with pytest.raises(HostManifestFreezeError, match="configured Host workload credential"):
        _discover_once(profile, context, None)


@pytest.mark.parametrize("cached_policy,expected_success", [(None, False), ("declared", True)])
def test_cached_manifest_must_match_declared_profile(
    monkeypatch,
    cached_policy: str | None,
    expected_success: bool,
) -> None:
    from agent_core.domain.host_connectors import HostConnectorProfileVersion
    from agent_integrations.host_tools import HostToolManifest
    from agent_storage.postgres import host_manifest_freeze as storage
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from zebra_agent_api.host_manifest_freeze import resolve_frozen_manifest

    profile = HostConnectorProfileVersion(
        host_app_id="neutral-product",
        connector_id="neutral-main",
        profile_revision=2,
        base_uri="https://neutral.example",
        manifest_path="/manifest",
        invoke_path_template="/invoke",
        supported_protocol_versions=("v1",),
        workload_identity_ref="workload/neutral",
        credential_ref="credentials/neutral",
        manifest_binding_policy="declared",
    )
    context = HostContextEnvelope(
        grant_id="g",
        host_app_id="neutral-product",
        namespace_id="neutral-ns",
        workspace_ref="workspace-neutral",
        resource_refs=(HostResourceRef(type="workspace", id="workspace-neutral"),),
        scopes=("record.read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=30, max_model_tokens=1000, max_artifact_bytes=1000
        ),
        origin="https://neutral.example",
        policy_version="v1",
    )
    manifest = HostToolManifest.from_payload(
        {
            "workloadIdentity": "workload/neutral",
            "tools": [
                {
                    "name": "records.read",
                    "scopes": ["record.read"],
                    "resourceBindings": [],
                }
            ],
        },
        binding_policy=cached_policy,
    )
    monkeypatch.setattr(PostgresHostConnectorRegistry, "resolve_binding", lambda *_: profile)
    monkeypatch.setattr(PostgresHostConnectorRegistry, "get_profile", lambda *_: profile)
    monkeypatch.setattr(storage, "load_frozen_manifest", lambda *a, **k: manifest.to_payload())
    settings = SimpleNamespace(
        deployment="cloud", storage_authority="postgresql", database_url="unused"
    )
    if expected_success:
        assert (
            resolve_frozen_manifest(settings, SimpleNamespace(), context) == manifest.to_payload()
        )
    else:
        with pytest.raises(HostManifestFreezeError, match="binding policy mismatch"):
            resolve_frozen_manifest(settings, SimpleNamespace(), context)


@pytest.mark.parametrize("policy", [None, "legacy", "declared"])
def test_admission_discovery_uses_versioned_profile_manifest_path(monkeypatch, policy) -> None:
    from agent_integrations.host_tools import HostToolGateway, HostToolTransportResponse

    from tests.agent_integrations.test_host_tools import _FakeTransport
    from tests.worker.test_host_egress import _context, _profile

    profile = _profile().model_copy(update={
        "manifest_path": "/capabilities", "manifest_binding_policy": policy,
    })
    transport = _FakeTransport([HostToolTransportResponse(200, {
        "workloadIdentity": profile.workload_identity_ref,
        "tools": [{"name": "record.read", "scopes": ["scope:a"], "resourceBindings": []}],
    })])
    discover = HostToolGateway.discover

    def use_transport(self, context):
        self.transport = transport
        return discover(self, context)

    monkeypatch.setattr(HostToolGateway, "discover", use_transport)
    _discover_once(profile, _context(), "test-secret")
    path = "/manifest" if policy is None else "/capabilities"
    assert transport.calls[0][1] == "https://pinned.example.com" + path
