"""Delegation contract tests: idempotency, narrowing, drift, overflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagent_delegation import (
    ChildCapabilityOverflowError,
    ChildResourceOverflowError,
    ParentBindingDriftError,
    ParentChildLink,
    SubagentDelegationReceipt,
    SubagentDelegationRequest,
    derive_child_binding,
)
from agent_core.domain.subagents import SubagentRole
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from pydantic import ValidationError

PARENT_CAPS = capability_set(["agent.execute", "evidence.read", "timeline.read"])


def _parent_binding() -> TaskBindingSnapshot:
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/parent@1",
        capabilities=PARENT_CAPS,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-a",
        authority_issuer="https://host-a.example.com",
        namespace_id="tenant-a",
        grant_digest="c" * 64,
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connector_id="host-a-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=PARENT_CAPS,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(TaskId(uuid4())),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=PARENT_CAPS,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


_FIXED_PARENT = TaskId(uuid4())


def _request(parent: TaskBindingSnapshot, **overrides: object) -> SubagentDelegationRequest:
    payload: dict[str, object] = {
        "parent_task_id": _FIXED_PARENT,
        "parent_attempt_number": 1,
        "parent_tool_call_id": "call-1",
        "delegation_index": 0,
        "role": SubagentRole.RESEARCHER,
        "objective": "Collect event evidence",
        "requested_capabilities": frozenset(capability_set(["evidence.read"])),
        "child_definition_snapshot_digest": "1" * 64,
        "child_capability_profile_ref": "profile/researcher@1",
        "expected_parent_binding_digest": parent.binding_digest,
    }
    payload.update(overrides)
    return SubagentDelegationRequest(**payload)  # type: ignore[arg-type]


class TestIdempotencyKey:
    def test_key_is_frozen_from_the_four_components(self) -> None:
        parent = _parent_binding()
        first = _request(parent)
        second = _request(parent)
        assert first.idempotency_key == second.idempotency_key
        assert len(first.idempotency_key) == 64

    def test_any_component_change_changes_the_key(self) -> None:
        parent = _parent_binding()
        base = _request(parent)
        assert (
            _request(parent, delegation_index=1).idempotency_key
            != base.idempotency_key
        )
        assert (
            _request(parent, parent_attempt_number=2).idempotency_key
            != base.idempotency_key
        )
        assert (
            _request(parent, parent_tool_call_id="call-2").idempotency_key
            != base.idempotency_key
        )

    def test_role_and_objective_do_not_change_the_key(self) -> None:
        parent = _parent_binding()
        base = _request(parent)
        assert (
            _request(parent, objective="Different objective").idempotency_key
            == base.idempotency_key
        )


class TestDerivation:
    def test_child_binding_narrows_below_parent(self) -> None:
        parent = _parent_binding()
        request = _request(parent)
        child = derive_child_binding(
            parent,
            request,
            child_task_id=TaskId(uuid4()),
            child_definition_ceiling=capability_set(
                ["evidence.read", "timeline.read", "extra.read"]
            ),
            zebra_child_policy_capabilities=capability_set(
                ["agent.execute", "evidence.read"]
            ),
        )
        assert child.effective_capabilities == capability_set(["evidence.read"])
        assert child.effective_capabilities < parent.effective_capabilities
        assert child.host_capability.namespace_id == "tenant-a"
        assert child.binding_digest != parent.binding_digest

    def test_capability_overflow_fails_closed(self) -> None:
        parent = _parent_binding()
        request = _request(
            parent,
            requested_capabilities=frozenset(capability_set(["host.business.write"])),
        )
        with pytest.raises(ChildCapabilityOverflowError):
            derive_child_binding(
                parent,
                request,
                child_task_id=TaskId(uuid4()),
                child_definition_ceiling=capability_set(["host.business.write"]),
                zebra_child_policy_capabilities=capability_set(["host.business.write"]),
            )

    def test_parent_digest_drift_fails_closed(self) -> None:
        parent = _parent_binding()
        request = _request(parent, expected_parent_binding_digest="0" * 64)
        with pytest.raises(ParentBindingDriftError):
            derive_child_binding(
                parent,
                request,
                child_task_id=TaskId(uuid4()),
                child_definition_ceiling=capability_set(["evidence.read"]),
                zebra_child_policy_capabilities=capability_set(["evidence.read"]),
            )

    def test_resource_overflow_fails_closed_when_refs_supplied(self) -> None:
        parent = _parent_binding()
        granted = frozenset(
            {HostResourceRef(type="host-a.event", id="evt-1")}
        )
        request = _request(
            parent,
            resource_refs=(HostResourceRef(type="host-a.event", id="evt-9"),),
        )
        with pytest.raises(ChildResourceOverflowError):
            derive_child_binding(
                parent,
                request,
                child_task_id=TaskId(uuid4()),
                child_definition_ceiling=capability_set(["evidence.read"]),
                zebra_child_policy_capabilities=capability_set(["evidence.read"]),
                parent_resource_refs=granted,
            )

    def test_empty_intersection_is_rejected(self) -> None:
        parent = _parent_binding()
        request = _request(parent)
        with pytest.raises(ValueError, match="empty capability"):
            derive_child_binding(
                parent,
                request,
                child_task_id=TaskId(uuid4()),
                child_definition_ceiling=capability_set(["unrelated.read"]),
                zebra_child_policy_capabilities=capability_set(["unrelated.read"]),
            )


class TestRecords:
    def test_request_requires_capabilities(self) -> None:
        parent = _parent_binding()
        with pytest.raises(ValidationError):
            _request(parent, requested_capabilities=frozenset())

    def test_link_and_receipt_shapes(self) -> None:
        link = ParentChildLink(
            root_task_id=TaskId(uuid4()),
            parent_task_id=TaskId(uuid4()),
            child_task_id=TaskId(uuid4()),
            delegation_id="a" * 64,
            parent_binding_digest="b" * 64,
            child_binding_digest="c" * 64,
            created_at=datetime.now(UTC),
        )
        assert link.terminal_at is None
        receipt = SubagentDelegationReceipt(
            delegation_id="a" * 64,
            idempotency_key="d" * 64,
            child_task_id=link.child_task_id,
            child_binding_digest="c" * 64,
        )
        assert receipt.status == "materialized"
        with pytest.raises(ValidationError):
            ParentChildLink(
                root_task_id=link.root_task_id,
                parent_task_id=link.parent_task_id,
                child_task_id=link.child_task_id,
                delegation_id="a" * 64,
                parent_binding_digest="b" * 64,
                created_at=datetime(2026, 8, 19, 12, 0),
            )
