"""Shared Host conformance suite (AL-HOST-CONFORMANCE-01).

Both fake Hosts — completely different business vocabularies — must pass
the SAME suite over the REAL parsing, binding resolution, admission,
effect and replay paths. Adding a Host must never require touching
agent-core or Worker production code.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.host_effect_receipts import HostEffectStatus
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall

sys.path.insert(0, str(Path(__file__).parent))

from fake_host import CONFORMANCE_HOSTS, FakeHost  # noqa: E402
from zebra_agent_worker.host_effect import (  # noqa: E402
    HostEffectReconciler,
    record_uncertain_write,
)

HOST_FACTORIES = {factory.__name__: factory for factory in CONFORMANCE_HOSTS}


def _call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=dict(arguments),
        created_at=datetime.now(UTC),
    )


@pytest.fixture(params=sorted(HOST_FACTORIES), ids=sorted(HOST_FACTORIES))
def host(request) -> FakeHost:
    return HOST_FACTORIES[request.param]()


class TestManifestAndBinding:
    def test_manifest_declares_bindings_without_legacy_inference(self, host: FakeHost) -> None:
        manifest = host.manifest()
        for tool, _cap, _scope, resource_type, argument, _write in host.tools:
            rules = manifest.resource_bindings_for(tool)
            assert rules, f"{tool} must declare its resource bindings"
            assert rules[0].argument_name == argument
            assert rules[0].resource_type == resource_type

    def test_manifest_growth_changes_digest_not_frozen_behaviour(self, host: FakeHost) -> None:
        original = host.manifest()
        payload = host.manifest_payload()
        grown = dict(payload)
        grown["tools"] = [*payload["tools"], dict(payload["tools"][0], name="extra.tool")]
        from agent_integrations.host_tools.contracts import HostToolManifest

        regrown = HostToolManifest.from_payload(grown)
        assert regrown.digest != original.digest
        # the original manifest and its declared bindings stay byte-identical
        assert HostToolManifest.from_payload(payload).digest == original.digest


class TestAdmission:
    def test_full_grant_admits_reads_without_business_writes(self, host: FakeHost) -> None:
        tool, _resource_type, argument = host.read_tool()
        context = host.full_grant()
        resource_id = f"{_resource_type_of(host, tool)}-1"
        result = host.invoke(_call(tool, **{argument: resource_id}), context)
        assert result == "read-acknowledged"
        assert host.business_snapshot == {}

    def test_missing_grant_scope_denies_and_writes_nothing(self, host: FakeHost) -> None:
        tool, resource_type, argument = host.read_tool()
        context = host.grant_context(
            scopes=("host:unrelated",),
            resources=(HostResourceRef(type=resource_type, id=f"{resource_type}-1"),),
        )
        from agent_integrations.host_tools.contracts import HostToolGatewayError

        with pytest.raises(HostToolGatewayError, match="scope"):
            host.invoke(_call(tool, **{argument: f"{resource_type}-1"}), context)
        assert host.business_snapshot == {}

    def test_ungranted_resource_denies_and_writes_nothing(self, host: FakeHost) -> None:
        tool, resource_type, argument = host.read_tool()
        scopes = tuple({scope for _t, _c, scope, *_ in host.tools})
        context = host.grant_context(
            scopes=scopes,
            resources=(HostResourceRef(type=resource_type, id="other-resource"),),
        )
        from agent_integrations.host_tools.contracts import HostToolGatewayError

        with pytest.raises(HostToolGatewayError, match="resource"):
            host.invoke(_call(tool, **{argument: f"{resource_type}-1"}), context)
        assert host.business_snapshot == {}

    def test_namespace_mismatch_denies_and_preserves_the_snapshot(self, host: FakeHost) -> None:
        tool, resource_type, argument = host.write_tool()
        context = host.full_grant()
        # simulate a drifted namespace grant
        drifted = host.grant_context(
            scopes=context.scopes,
            resources=context.resource_refs,
        )
        object.__setattr__(drifted, "namespace_id", "other-tenant")
        from agent_integrations.host_tools.contracts import HostToolGatewayError

        with pytest.raises((HostToolGatewayError, ValueError)):
            host.invoke_drifted(_call(tool, **{argument: f"{resource_type}-1"}), drifted)
        assert host.business_snapshot == {}


class TestWriteEffects:
    def test_write_timeout_records_uncertain_then_reconciles(self, host: FakeHost) -> None:
        tool, resource_type, argument = host.write_tool()
        host.simulated_write_timeouts.add(tool)
        context = host.full_grant()
        assert host.invoke(_call(tool, **{argument: f"{resource_type}-1"}), context) == "uncertain"
        assert host.business_snapshot == {}

        operation_id = f"conf-{uuid4()}"
        outcome = record_uncertain_write(operation_id)
        assert outcome.receipt.effect_status is HostEffectStatus.UNCERTAIN

        class _Transport:
            def request(self, url, *, provider_operation_id, timeout_seconds):
                host.business_snapshot[provider_operation_id] = "written"
                return 200, {
                    "effectStatus": "succeeded",
                    "businessRevision": "rev-conf-1",
                }

        settled = HostEffectReconciler(_Transport()).reconcile(
            _reconcile_profile(host), outcome.receipt
        )
        assert settled.effect_status is HostEffectStatus.SUCCEEDED
        assert settled.business_revision == "rev-conf-1"
        assert operation_id in host.business_snapshot

    def test_successful_write_lands_in_the_business_snapshot(self, host: FakeHost) -> None:
        tool, resource_type, argument = host.write_tool()
        context = host.full_grant()
        host.invoke(_call(tool, **{argument: f"{resource_type}-1"}), context)
        assert any(key.startswith(tool) for key in host.business_snapshot)


def _resource_type_of(host: FakeHost, tool: str) -> str:
    return next(item[3] for item in host.tools if item[0] == tool)


def _reconcile_profile(host: FakeHost):
    from agent_core.domain.host_connectors import HostConnectorProfileVersion

    return HostConnectorProfileVersion(
        host_app_id=host.host_app_id,
        connector_id=f"{host.host_app_id}-main",
        profile_revision=1,
        base_uri=f"https://{host.host_app_id}.example.com",
        manifest_path="/manifest",
        invoke_path_template="/tools/invoke",
        reconcile_path_template="/tools/reconcile",
        supported_protocol_versions=("host-capability-protocol/1",),
        workload_identity_ref="workload/zebra-worker",
        credential_ref=f"credentials/{host.host_app_id}",
    )


class TestZeroBranchGate:
    def test_production_code_carries_no_fake_host_vocabulary(self) -> None:
        roots = (
            Path(__file__).parents[3] / "packages" / "agent-core" / "src",
            Path(__file__).parents[3] / "apps" / "worker" / "src",
        )
        forbidden = ("catalog.item.read", "workflow.note.write", "conf-host")
        for root in roots:
            for source in root.rglob("*.py"):
                text = source.read_text(encoding="utf-8")
                for token in forbidden:
                    assert token not in text, f"{source} mentions {token}"

    def test_both_hosts_use_this_one_suite(self) -> None:
        hosts = [factory() for factory in HOST_FACTORIES.values()]
        assert len(hosts) == 2
        vocabularies = {
            tuple(sorted({item[1] for item in host.tools})) for host in hosts
        }
        assert len(vocabularies) == 2, "conformance hosts must differ in vocabulary"
