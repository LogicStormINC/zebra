"""Explicit discovery is trusted configuration; historical freezes retain their hashes."""

from __future__ import annotations

from copy import deepcopy

import pytest
from agent_integrations.host_tools import (
    HostToolGateway,
    HostToolGatewayError,
    HostToolManifest,
    HostToolTransportResponse,
    HostWorkloadIdentity,
)

from tests.agent_integrations.test_host_tools import _context, _FakeTransport

GOLDEN_DIGEST = "5082cc40e9ff8e5ac317789449a800fd7a54ad5f3b61fb20952746abdcdcf2a6"


def _payload() -> dict:
    return {
        "workloadIdentity": "trench-worker",
        "tools": [
            {
                "name": "events.get_event",
                "description": "read",
                "requiredArguments": ["event_id"],
                "argumentProperties": {"event_id": {"type": "string"}},
                "scopes": ["scope:a"],
                "resourceBindings": [],
            }
        ],
    }


def test_empty_declaration_survives_freeze_without_name_inference() -> None:
    manifest = HostToolManifest.from_payload(_payload(), binding_policy="declared")
    frozen = manifest.to_payload()
    assert frozen["bindingPolicy"] == "declared"
    assert frozen["tools"][0]["resourceBindings"] == []
    restored = HostToolManifest.from_payload(frozen)
    assert restored == manifest
    assert restored.resource_bindings_for("events.get_event") == ()
    # A marker is part of the digest, so stripping it cannot downgrade a frozen manifest.
    del frozen["bindingPolicy"]
    with pytest.raises(HostToolGatewayError, match="digest"):
        HostToolManifest.from_payload(frozen)


def test_every_tool_requires_a_declaration_and_host_cannot_downgrade() -> None:
    payload = _payload()
    del payload["tools"][0]["resourceBindings"]
    gateway = HostToolGateway(
        "https://host.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=_FakeTransport([HostToolTransportResponse(200, payload)]),
    )
    with pytest.raises(HostToolGatewayError, match="each tool"):
        gateway.discover(_context())
    payload["bindingPolicy"] = "legacy"
    gateway.transport = _FakeTransport([HostToolTransportResponse(200, payload)])
    with pytest.raises(HostToolGatewayError, match="unknown"):
        gateway.discover(_context())
    del payload["bindingPolicy"]
    gateway.manifest_binding_policy = "legacy"
    gateway.transport = _FakeTransport([HostToolTransportResponse(200, payload)])
    assert gateway.discover(_context()).resource_bindings_for("events.get_event")


@pytest.mark.parametrize("required", ["false", "true", 0, 1, None, [], {}])
def test_declared_required_never_coerces(required: object) -> None:
    payload = _payload()
    payload["tools"][0]["resourceBindings"] = [
        {
            "argumentPointer": "/event_id",
            "resourceType": "opaque.record",
            "required": required,
        }
    ]
    with pytest.raises(HostToolGatewayError, match="boolean"):
        HostToolManifest.from_payload(payload, binding_policy="declared")


@pytest.mark.parametrize("mode", ["prefix", "", None, 0, True])
def test_declared_match_mode_is_validated(mode: object) -> None:
    payload = _payload()
    payload["tools"][0]["resourceBindings"] = [
        {
            "argumentPointer": "/event_id",
            "resourceType": "opaque.record",
            "matchMode": mode,
        }
    ]
    with pytest.raises(HostToolGatewayError, match="binding entry"):
        HostToolManifest.from_payload(payload, binding_policy="declared")


def test_declared_typed_rule_round_trip_and_historical_coercion() -> None:
    payload = _payload()
    payload["tools"][0]["resourceBindings"] = [
        {
            "argumentPointer": "/event_id",
            "resourceType": "opaque.record",
            "required": False,
            "matchMode": "exact",
        }
    ]
    manifest = HostToolManifest.from_payload(payload, binding_policy="declared")
    assert not manifest.resource_bindings_for("events.get_event")[0].required
    assert HostToolManifest.from_payload(manifest.to_payload()) == manifest
    payload["tools"][0]["resourceBindings"][0].update(required="false", matchMode="prefix")
    historical = HostToolManifest.from_payload(payload)
    rule = historical.resource_bindings_for("events.get_event")[0]
    assert rule.required is True and rule.match_mode == "exact"


def test_unmarked_historical_manifest_keeps_exact_digest_and_wire_shape() -> None:
    payload = _payload()
    payload["workloadIdentity"] = "zebra-worker"
    del payload["tools"][0]["resourceBindings"]
    manifest = HostToolManifest.from_payload(payload)
    assert manifest.digest == GOLDEN_DIGEST
    frozen = manifest.to_payload()
    assert "bindingPolicy" not in frozen
    assert "resourceBindings" not in frozen["tools"][0]
    assert HostToolManifest.from_payload(deepcopy(frozen)) == manifest
    assert manifest.resource_bindings_for("events.get_event")[0].resource_type == "trench.event"


@pytest.mark.parametrize("marker", ["legacy", "unknown", None, 1, False])
def test_unknown_frozen_marker_rejected(marker: object) -> None:
    payload = _payload()
    payload["bindingPolicy"] = marker
    with pytest.raises(HostToolGatewayError, match="unknown"):
        HostToolManifest.from_payload(payload)
