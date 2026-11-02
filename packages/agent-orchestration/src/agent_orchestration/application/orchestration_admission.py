"""Exact child inputs and original receipts for the orchestration admission use case."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagent_delegation import SubagentDelegationRequest, derive_child_binding
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest

from agent_orchestration.application.orchestration_authority import OrchestrationAuthority
from agent_orchestration.application.orchestration_port import (
    OrchestrationToolError,
    TaskRequestReceipt,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeProposal,
    OrchestrationPlanSnapshot,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def original_key(namespace: str, snapshot: OrchestrationPlanSnapshot, node_key: str) -> str:
    return digest(
        [
            namespace,
            str(snapshot.parent_task_id),
            snapshot.run_ref,
            snapshot.plan_revision,
            node_key,
        ]
    )


def semantic_digest(namespace: str, snapshot: OrchestrationPlanSnapshot, node_key: str) -> str:
    # Existing plan_digest intentionally omits objectives, role and per-node limits.
    # Admission binds the COMPLETE frozen request, not that projection digest.
    value = snapshot.model_dump(mode="json")
    for node in value["nodes"]:
        node["proposal"]["required_capabilities"].sort()
    return digest([original_key(namespace, snapshot, node_key), value])


def node_budget(node: OrchestrationNodeProposal) -> BudgetReservation:
    return BudgetReservation(
        model_tokens=node.max_model_tokens,
        tool_calls=node.max_tool_calls,
        runtime_seconds=node.max_runtime_seconds,
    )


def derive_orchestration_child_binding(
    parent: TaskBindingSnapshot,
    request: SubagentDelegationRequest,
    child_id: UUID,
    node: OrchestrationNodeProposal,
    *,
    parent_resource_refs: frozenset[HostResourceRef] | None = None,
) -> TaskBindingSnapshot:
    """Derive ordinary child authority and tighten its effective technical limits."""
    context = parent.host_capability.host_context
    if context is None or node.max_model_tokens <= 0 or node.max_runtime_seconds <= 0:
        # ponytail: HostTechnicalLimits cannot represent zero. Refuse rather
        # than rounding it up; a zero-capable executor contract belongs to 03C.
        raise OrchestrationToolError("invalid_child", "positive representable Host limits required")
    if (
        node.max_model_tokens > context.limits.max_model_tokens
        or node.max_runtime_seconds > context.limits.max_runtime_seconds
    ):
        raise OrchestrationToolError("invalid_child", "node limits exceed current Host limits")
    child = derive_child_binding(
        parent,
        request,
        child_task_id=TaskId(child_id),
        child_definition_ceiling=node.required_capabilities,
        zebra_child_policy_capabilities=node.required_capabilities,
        parent_resource_refs=parent_resource_refs,
    )
    limits = context.limits.model_copy(
        update={
            "max_model_tokens": node.max_model_tokens,
            "max_runtime_seconds": node.max_runtime_seconds,
        }
    )
    if set(node.resource_refs) - set(context.resource_refs):
        raise OrchestrationToolError(
            "invalid_child", "node resources exceed frozen parent Host scope"
        )
    principals = tuple(ref for ref in context.resource_refs if ref.resource_type == "principal")
    if len(principals) != 1:
        raise OrchestrationToolError(
            "invalid_child", "one parent principal is required for lineage"
        )
    refs = tuple(dict.fromkeys((*principals, *node.resource_refs)))
    narrowed = context.model_copy(update={"limits": limits, "resource_refs": refs})
    host = child.host_capability.model_copy(
        update={"host_context": narrowed, "grant_digest": host_context_digest(narrowed)}
    )
    return child.model_copy(update={"host_capability": host})


@dataclass(frozen=True)
class PreparedOrchestrationChild:
    """Trusted local builder output, checked against the frozen node before persistence."""

    delegation: SubagentDelegationRequest
    admission: TaskAdmissionRequest

    def payload(self) -> dict[str, Any]:
        request = self.admission
        if request.idempotency is not None or request.input_artifacts:
            # ponytail: this slice has no child upload/idempotency adapter; add explicit
            # serialization and authorization before allowing these separate inputs.
            raise OrchestrationToolError("invalid_child", "extra admission inputs are unsupported")
        return {
            "delegation": self.delegation.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in request.events],
            "session": request.session.model_dump(mode="json"),
            "workspace": request.workspace.model_dump(mode="json"),
            "binding": request.binding.model_dump(mode="json") if request.binding else None,
        }

    def validate(
        self,
        authority: OrchestrationAuthority,
        parent: TaskBindingSnapshot,
        snapshot: OrchestrationPlanSnapshot,
        node: OrchestrationNodeProposal,
    ) -> None:
        request, admission = self.delegation, self.admission
        key = original_key(authority.deployment_namespace, snapshot, node.node_key)
        if (
            request.parent_task_id != authority.parent_task_id
            or request.expected_parent_binding_digest != authority.parent_binding_digest
            or request.parent_attempt_number != 1
            or request.parent_tool_call_id != key
            or request.delegation_index != 0
            or request.objective != node.objective
            or request.role.value != node.preferred_agent_role
            or request.requested_capabilities != node.required_capabilities
            or tuple(request.resource_refs) != tuple(node.resource_refs)
            or request.isolation_mode != node.isolation_mode
        ):
            raise OrchestrationToolError("invalid_child", "child input disagrees with frozen node")
        if parent.host_capability.host_context is None:
            raise OrchestrationToolError("invalid_child", "Host scope is required for stop lineage")
        admission.validate()
        if admission.binding is None or str(admission.session.session_id) == parent.task_id:
            raise OrchestrationToolError("invalid_child", "child binding is required")
        expected = derive_orchestration_child_binding(
            parent,
            request,
            admission.session.session_id,
            node,
            parent_resource_refs=authority.validation.parent_resource_refs,
        )
        # Compare every authority-bearing field, not only binding_digest (which
        # deliberately omits some Host context and ceiling fields).
        actual = admission.binding.model_dump(mode="json")
        fixed = expected.model_dump(mode="json")
        for value in (actual, fixed):
            value.pop("bound_at")
            value["agent_capability_ceiling"].pop("resolved_at")
        if actual != fixed:
            raise OrchestrationToolError("invalid_child", "child binding does not narrow parent")

        expected_context = expected.host_capability.host_context
        assert expected_context is not None  # guaranteed by the narrowing helper
        prepared = [e for e in admission.events if e.event_type is EventType.TASK_PREPARED]
        runs = [e for e in admission.events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]
        if (
            len(prepared) != 1
            or len(runs) != 1
            or runs[0] is not admission.events[-1]
            or runs[0].payload.get("kind") != "run"
            or prepared[0].payload.get("max_model_calls") != node.max_model_calls
            or prepared[0].payload.get("max_tool_calls") != node.max_tool_calls
            or prepared[0].payload.get("user_input") != node.objective
            or prepared[0].payload.get("host_context")
            != expected_context.model_dump(mode="json", exclude_none=True)
        ):
            raise OrchestrationToolError(
                "invalid_child", "initial RUN and exact node limits required"
            )
        self.payload()


class OrchestrationAdmissionPort(Protocol):
    """Bound server service: obtains fresh authority for its own short transactions."""

    def request_task(self, *, run_ref: str, node_key: str) -> TaskRequestReceipt: ...
