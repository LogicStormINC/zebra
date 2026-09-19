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
