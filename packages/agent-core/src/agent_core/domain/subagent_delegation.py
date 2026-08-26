"""Parent-to-child delegation contracts (SUBAGENT-DELEGATION-CON-01).

Plan section 8: cloud delegation is durable and idempotent. The idempotency
key is frozen from (parent_task_id, parent_attempt_number,
parent_tool_call_id, delegation_index); the same request replayed must
return the same child. Child bindings are DERIVED — capabilities, resources
and limits can only narrow below the parent's frozen binding.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.agent_capabilities import (
    Capability,
    capability_set,
    intersect_capabilities,
)
from agent_core.domain.context_inheritance import ContextInheritanceMode
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagents import SubagentRole
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    TaskBindingSnapshot,
)

MAX_OBJECTIVE_LENGTH = 4096


class DelegationReplayError(ValueError):
    """The same idempotency key resolved to a different delegation."""


class ParentBindingDriftError(ValueError):
    """The parent binding digest moved under an in-flight delegation."""


class ChildCapabilityOverflowError(ValueError):
    """A delegation requested capabilities beyond the parent binding."""


class ChildResourceOverflowError(ValueError):
    """A delegation requested resources beyond the parent binding."""


class SubagentDelegationRequest(BaseModel):
    """One durable parent→child delegation ask (plan 7.1/8.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_task_id: TaskId
    parent_attempt_number: int = Field(ge=1)
    parent_tool_call_id: str = Field(min_length=1, max_length=128)
    delegation_index: int = Field(ge=0)
    role: SubagentRole
    objective: str = Field(min_length=1, max_length=MAX_OBJECTIVE_LENGTH)
    context_mode: ContextInheritanceMode = ContextInheritanceMode.FRESH
    isolation_mode: Literal["shared_readonly", "worktree", "snapshot", "none"] = (
        "shared_readonly"
    )
    requested_capabilities: frozenset[Capability]
    resource_refs: tuple[HostResourceRef, ...] = ()
    child_definition_snapshot_digest: str = Field(min_length=64, max_length=64)
    child_capability_profile_ref: str = Field(min_length=1, max_length=256)
    expected_parent_binding_digest: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        object.__setattr__(
            self,
            "requested_capabilities",
            capability_set(sorted(self.requested_capabilities)),
        )
        if not self.requested_capabilities:
            raise ValueError("delegation must request at least one capability")
        return self

    @property
    def idempotency_key(self) -> str:
        """Frozen replay key — identical requests must resolve identically."""

        canonical = {
            "parentTaskId": str(self.parent_task_id),
            "parentAttempt": self.parent_attempt_number,
            "parentToolCallId": self.parent_tool_call_id,
            "delegationIndex": self.delegation_index,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class ParentChildLink(BaseModel):
    """The durable lineage edge (plan 13.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace_implicit: Literal[""] = ""
    root_task_id: TaskId
    parent_task_id: TaskId
    child_task_id: TaskId
    delegation_id: str = Field(min_length=64, max_length=64)
    plan_revision: int | None = Field(default=None, ge=1)
    node_key: str | None = Field(default=None, max_length=128)
    parent_binding_digest: str = Field(min_length=64, max_length=64)
    child_binding_digest: str | None = Field(default=None, min_length=64, max_length=64)
    created_at: datetime
    terminal_at: datetime | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        for stamp in (self.created_at, self.terminal_at):
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError("link timestamps must be timezone-aware")
        return self


class SubagentDelegationReceipt(BaseModel):
    """What the parent receives once the child is durably materialized."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delegation_id: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=64, max_length=64)
    child_task_id: TaskId
    child_binding_digest: str = Field(min_length=64, max_length=64)
    status: Literal["materialized", "replayed"] = "materialized"


def derive_child_binding(
    parent: TaskBindingSnapshot,
    request: SubagentDelegationRequest,
    *,
    child_task_id: TaskId,
    child_definition_ceiling: frozenset[Capability],
    zebra_child_policy_capabilities: frozenset[Capability],
    parent_resource_refs: frozenset[HostResourceRef] | None = None,
) -> TaskBindingSnapshot:
    """Derive the child binding — narrowing only, never expanding (7.2)."""

    if parent.binding_digest != request.expected_parent_binding_digest:
        raise ParentBindingDriftError(
            "parent binding digest drifted before delegation was derived"
        )
    requested = request.requested_capabilities
    if requested - parent.effective_capabilities:
        raise ChildCapabilityOverflowError(
            "delegation requests capabilities beyond the parent binding"
        )
    if parent_resource_refs is not None:
        requested_refs = set(request.resource_refs)
        if requested_refs - set(parent_resource_refs):
            raise ChildResourceOverflowError(
                "delegation requests resources beyond the parent binding"
            )
    child_ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest=request.child_definition_snapshot_digest,
        capability_profile_ref=request.child_capability_profile_ref,
        capabilities=child_definition_ceiling,
        resolved_at=datetime.now(UTC),
    )
    child_host = parent.host_capability.model_copy(
        update={
            "capabilities": capability_set(
                sorted(requested & parent.host_capability.capabilities)
            ),
        }
    )
    binding = TaskBindingSnapshot(
        task_id=str(child_task_id),
        agent_capability_ceiling=child_ceiling,
        host_capability=child_host,
        zebra_policy_digest=parent.zebra_policy_digest,
        effective_capabilities=intersect_capabilities(
            parent.effective_capabilities,
            child_definition_ceiling,
            requested,
            zebra_child_policy_capabilities,
        ),
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )
    if not binding.effective_capabilities:
        raise ValueError("child delegation narrows to an empty capability set")
    return binding
