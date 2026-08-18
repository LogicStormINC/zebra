"""Host capability contract tests: digests, selectors, receipts, capabilities."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.agent_capabilities import (
    capability,
    capability_set,
    grant_scope,
    intersect_capabilities,
)
from agent_core.domain.host_capability_manifests import (
    MANIFEST_SCHEMA_VERSION,
    HostCapabilityManifestV1,
    HostToolContractV1,
    ResourceBindingRule,
)
from agent_core.domain.host_effect_receipts import (
    HostEffectReceipt,
    HostEffectStatus,
    uncertain_receipt,
)
from pydantic import ValidationError


class TestCapabilityVocabulary:
    def test_stable_dotted_names_are_accepted(self) -> None:
        assert capability("evidence.read") == "evidence.read"
        assert capability(" timeline.read ") == "timeline.read"

    def test_host_wording_stays_a_grant_scope(self) -> None:
        assert grant_scope("trench:event:read") == "trench:event:read"
        assert grant_scope("jazz:project:write") == "jazz:project:write"

    def test_capability_rejects_non_dotted_or_blank(self) -> None:
        for invalid in ("", "   ", "read", "Evidence.Read", "a. b"):
            with pytest.raises(ValueError):
                capability(invalid)

    def test_capability_set_rejects_duplicates(self) -> None:
        with pytest.raises(ValueError):
            capability_set(["evidence.read", "evidence.read"])

    def test_intersection_authorises_only_the_overlap(self) -> None:
        ceiling = capability_set(["evidence.read", "timeline.read", "report.write"])
        granted = capability_set(["evidence.read", "timeline.read"])
        policy = capability_set(["timeline.read", "report.write"])
        assert intersect_capabilities(ceiling, granted, policy) == capability_set(
            ["timeline.read"]
        )


class TestResourceBindingRule:
    def test_single_segment_pointer_exposes_argument_name(self) -> None:
        rule = ResourceBindingRule(
            argument_pointer="/event_id",
            resource_type="trench.event",
        )
        assert rule.argument_name == "event_id"
        assert rule.required is True
        assert rule.match_mode == "exact"

    def test_executable_selectors_are_rejected(self) -> None:
        for pointer in ("/a/b", "$..event", "/a[0]", "event_id", "/a b", "/x/y/z"):
            with pytest.raises(ValidationError):
                ResourceBindingRule(argument_pointer=pointer, resource_type="t.x")


class TestHostToolContractV1:
    def test_digest_is_canonical_and_deterministic(self) -> None:
        first = HostToolContractV1(
            name="events.get_event",
            capabilities=frozenset({"evidence.read"}),
            required_grant_scopes=frozenset({"trench:event:read"}),
            resource_bindings=(
                ResourceBindingRule(argument_pointer="/event_id", resource_type="trench.event"),
            ),
        )
        second = HostToolContractV1(
            name="events.get_event",
            capabilities=frozenset({"evidence.read"}),
            required_grant_scopes=frozenset({"trench:event:read"}),
            resource_bindings=(
                ResourceBindingRule(argument_pointer="/event_id", resource_type="trench.event"),
            ),
        )
        assert first.contract_digest == second.contract_digest
        assert len(first.contract_digest) == 64

    def test_contract_requires_at_least_one_capability(self) -> None:
        with pytest.raises(ValidationError):
            HostToolContractV1(name="noop", capabilities=frozenset())


class TestHostCapabilityManifestV1:
    def _manifest(self) -> HostCapabilityManifestV1:
        return HostCapabilityManifestV1(
            schema_version=MANIFEST_SCHEMA_VERSION,
            protocol_version="host-capability-protocol/1",
            host_app_id="trench",
            connector_profile_revision=3,
            workload_identity="zebra-worker",
            tools=(
                HostToolContractV1(
                    name="events.get_event",
                    capabilities=frozenset({"evidence.read"}),
                    required_grant_scopes=frozenset({"trench:event:read"}),
                    resource_bindings=(
                        ResourceBindingRule(
                            argument_pointer="/event_id", resource_type="trench.event"
                        ),
                    ),
                ),
            ),
        )

    def test_manifest_digest_pins_contract_digests(self) -> None:
        manifest = self._manifest()
        assert len(manifest.manifest_digest) == 64
        rebuilt = self._manifest()
        assert manifest.manifest_digest == rebuilt.manifest_digest

    def test_duplicate_tool_names_are_rejected(self) -> None:
        tool = HostToolContractV1(
            name="dup",
            capabilities=frozenset({"evidence.read"}),
            required_grant_scopes=frozenset(),
        )
        with pytest.raises(ValidationError):
            HostCapabilityManifestV1(
                schema_version=MANIFEST_SCHEMA_VERSION,
                protocol_version="host-capability-protocol/1",
                host_app_id="trench",
                connector_profile_revision=1,
                workload_identity="zebra-worker",
                tools=(tool, tool),
            )


class TestHostEffectReceipt:
    def test_uncertain_receipt_pending_reconciliation(self) -> None:
        receipt = uncertain_receipt("op-123")
        assert receipt.effect_status is HostEffectStatus.UNCERTAIN
        assert not receipt.reconciled
        assert len(receipt.receipt_digest) == 64

    def test_succeeded_requires_business_revision(self) -> None:
        with pytest.raises(ValidationError):
            HostEffectReceipt(
                provider_operation_id="op-1",
                effect_status=HostEffectStatus.SUCCEEDED,
                received_at=datetime.now(UTC),
            )

    def test_receipts_reject_naive_timestamps(self) -> None:
        with pytest.raises(ValidationError):
            HostEffectReceipt(
                provider_operation_id="op-1",
                effect_status=HostEffectStatus.UNCERTAIN,
                received_at=datetime(2026, 8, 18, 12, 0),
            )
