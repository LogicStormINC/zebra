"""Task binding snapshot tests: intersection, digests, freezing semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.host_capability_manifests import (
    MANIFEST_SCHEMA_VERSION,
    HostCapabilityManifestV1,
    HostToolContractV1,
    ResourceBindingRule,
)
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    bind_task,
    compute_effective_capabilities,
)
from pydantic import ValidationError

CEILING_CAPS = capability_set(["evidence.read", "timeline.read", "report.write"])
HOST_CAPS = capability_set(["evidence.read", "timeline.read", "catalog.read"])
POLICY_CAPS = capability_set(["evidence.read", "timeline.read", "note.write"])


def _ceiling() -> AgentCapabilityCeilingSnapshot:
    return AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/default@1",
        capabilities=CEILING_CAPS,
        resolved_at=datetime.now(UTC),
    )


def _host_snapshot(manifest_digest: str = "b" * 64) -> HostCapabilitySnapshot:
    return HostCapabilitySnapshot(
        host_app_id="host-a",
        authority_issuer="https://host-a.example.com",
        namespace_id="tenant-a",
        grant_digest="c" * 64,
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connector_id="host-a-main",
        connector_profile_revision=2,
        connector_profile_digest="d" * 64,
        manifest_digest=manifest_digest,
        capabilities=HOST_CAPS,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )


class TestIntersection:
    def test_effective_capabilities_intersect_all_sources(self) -> None:
        effective = compute_effective_capabilities(
            _ceiling(),
            _host_snapshot(),
            zebra_policy_capabilities=POLICY_CAPS,
        )
        assert effective == capability_set(["evidence.read", "timeline.read"])

    def test_empty_intersection_is_rejected_at_binding(self) -> None:
        with pytest.raises(ValueError, match="empty capability intersection"):
            bind_task(
                "task-1",
                ceiling=_ceiling(),
                host=_host_snapshot(),
                zebra_policy_digest="f" * 64,
                zebra_policy_capabilities=capability_set(["unrelated.read"]),
            )

    def test_binding_digest_is_deterministic_and_pinned(self) -> None:
        first = bind_task(
            "task-1",
            ceiling=_ceiling(),
            host=_host_snapshot(),
            zebra_policy_digest="f" * 64,
            zebra_policy_capabilities=POLICY_CAPS,
        )
        second = bind_task(
            "task-1",
            ceiling=_ceiling(),
            host=_host_snapshot(),
            zebra_policy_digest="f" * 64,
            zebra_policy_capabilities=POLICY_CAPS,
        )
        assert first.binding_digest == second.binding_digest
        assert first.binding_revision == 1
        assert len(first.binding_digest) == 64

    def test_manifest_drift_changes_binding_digest(self) -> None:
        base = bind_task(
            "task-1",
            ceiling=_ceiling(),
            host=_host_snapshot(),
            zebra_policy_digest="f" * 64,
            zebra_policy_capabilities=POLICY_CAPS,
        )
        drifted = bind_task(
            "task-1",
            ceiling=_ceiling(),
            host=_host_snapshot(manifest_digest="0" * 64),
            zebra_policy_digest="f" * 64,
            zebra_policy_capabilities=POLICY_CAPS,
        )
        assert base.binding_digest != drifted.binding_digest


class TestHostSnapshotFromManifest:
    def test_manifest_freezes_capabilities_and_binding_digest(self) -> None:
        manifest = HostCapabilityManifestV1(
            schema_version=MANIFEST_SCHEMA_VERSION,
            protocol_version="host-capability-protocol/1",
            host_app_id="host-a",
            connector_profile_revision=4,
            workload_identity="zebra-worker",
            tools=(
                HostToolContractV1(
                    name="events.read",
                    capabilities=frozenset({"evidence.read"}),
                    required_grant_scopes=frozenset({"host-a:event:read"}),
                    resource_bindings=(
                        ResourceBindingRule(
                            argument_pointer="/event_id", resource_type="host-a.event"
                        ),
                    ),
                ),
            ),
        )
        snapshot = HostCapabilitySnapshot.from_manifest(
            manifest,
            authority_issuer="https://host-a.example.com",
            namespace_id="tenant-a",
            grant_digest="c" * 64,
            grant_expires_at=None,
            connector_id="host-a-main",
            connector_profile_digest="d" * 64,
        )
        assert snapshot.capabilities == capability_set(["evidence.read"])
        assert snapshot.manifest_digest == manifest.manifest_digest
        assert snapshot.connector_profile_revision == 4
        assert len(snapshot.resource_binding_digest) == 64


class TestSnapshotValidation:
    def test_snapshots_reject_naive_timestamps(self) -> None:
        with pytest.raises(ValidationError):
            AgentCapabilityCeilingSnapshot(
                definition_snapshot_digest="a" * 64,
                capability_profile_ref="p@1",
                capabilities=CEILING_CAPS,
                resolved_at=datetime(2026, 8, 18, 12, 0),
            )
