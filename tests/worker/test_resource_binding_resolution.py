"""Generic resource binding resolution and manifest binding parsing tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.host_capability_manifests import ResourceBindingRule
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_integrations.host_tools.contracts import HostToolManifest
from zebra_agent_worker.resource_binding import resolve_required_resource


def _context(*refs: HostResourceRef) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="host-a",
        namespace_id="ns-1",
        workspace_ref="workspace://w",
        resource_refs=refs,
        scopes=("scope:a",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=100_000,
            max_artifact_bytes=10_485_760,
        ),
        origin="https://host-a.example.com",
        policy_version="policy-v1",
    )


def _call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=dict(arguments),
        created_at=datetime.now(UTC),
    )


class TestResolveRequiredResource:
    def test_matched_resource_returns_the_granted_ref(self) -> None:
        granted = HostResourceRef(type="host-a.event", id="evt-1")
        rules = (ResourceBindingRule(argument_pointer="/event_id", resource_type="host-a.event"),)
        resolved = resolve_required_resource(
            rules, _call("tools.read", event_id="evt-1"), _context(granted)
        )
        assert resolved == granted

    def test_unmatched_resource_yields_typed_ref_for_denial(self) -> None:
        rules = (ResourceBindingRule(argument_pointer="/event_id", resource_type="host-a.event"),)
        context = _context(HostResourceRef(type="host-a.event", id="other"))
        resolved = resolve_required_resource(rules, _call("tools.read", event_id="evt-1"), context)
        assert resolved == HostResourceRef(type="host-a.event", id="evt-1")
        assert resolved not in context.resource_refs

    def test_missing_required_argument_yields_invalid_ref(self) -> None:
        rules = (ResourceBindingRule(argument_pointer="/event_id", resource_type="host-a.event"),)
        resolved = resolve_required_resource(
            rules, _call("tools.read"), _context(HostResourceRef(type="other", id="x"))
        )
        assert resolved == HostResourceRef(type="host-a.event", id="invalid")

    def test_no_required_rules_means_no_resource_requirement(self) -> None:
        context = _context(HostResourceRef(type="other", id="x"))
        optional = (ResourceBindingRule(argument_pointer="/x", resource_type="t", required=False),)
        assert resolve_required_resource(optional, _call("tools.read"), context) is None
        assert resolve_required_resource((), _call("tools.read"), context) is None


class TestManifestBindingParsing:
    def _payload(self, *, with_bindings: bool) -> dict[str, object]:
        tool: dict[str, object] = {
            "name": "events.get_event",
            "description": "read",
            "requiredArguments": ["event_id"],
            "argumentProperties": {"event_id": {"type": "string"}},
            "scopes": ["scope:a"],
        }
        if with_bindings:
            tool["resourceBindings"] = [
                {
                    "argumentPointer": "/event_id",
                    "resourceType": "declared.event",
                    "required": True,
                    "matchMode": "exact",
                }
            ]
        return {"workloadIdentity": "zebra-worker", "tools": [tool]}

    def test_declared_bindings_win_over_legacy_inference(self) -> None:
        manifest = HostToolManifest.from_payload(self._payload(with_bindings=True))
        rules = manifest.resource_bindings_for("events.get_event")
        assert rules
        assert rules[0].resource_type == "declared.event"

    def test_legacy_manifest_gets_inferred_bindings(self) -> None:
        manifest = HostToolManifest.from_payload(self._payload(with_bindings=False))
        rules = manifest.resource_bindings_for("events.get_event")
        assert rules
        assert rules[0].argument_name == "event_id"
        assert rules[0].resource_type == "trench.event"

    def test_invalid_binding_entry_is_rejected(self) -> None:
        payload = self._payload(with_bindings=True)
        payload["tools"][0]["resourceBindings"] = [  # type: ignore[index]
            {"argumentPointer": "$..event", "resourceType": "x"}
        ]
        with pytest.raises(Exception, match="resource binding"):
            HostToolManifest.from_payload(payload)
