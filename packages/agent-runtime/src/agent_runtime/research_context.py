"""Cloud-only durable research delegation and Context inheritance."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from agent_context import delegated_context_from_materialization
from agent_core.domain.context_inheritance import ContextInheritanceMode
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.identifiers import TaskId
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError


def durable_research_contract(base: ToolContract) -> ToolContract:
    return replace(
        base,
        description=(
            base.description
            + " Cloud children may explicitly choose fresh, capsule, fork_tail, or "
            "resume; every inherited mode is bounded and source-attributed."
        ),
        argument_properties={
            **base.argument_properties,
            "context_mode": {
                "type": "string",
                "enum": [mode.value for mode in ContextInheritanceMode],
                "default": ContextInheritanceMode.FRESH.value,
                "description": (
                    "fresh=objective only; capsule=active parent capsule; "
                    "fork_tail=recent parent messages; resume=bounded capsule, tail, "
                    "and confirmed memory"
                ),
            },
        },
    )


def parse_context_mode(
    tool_call: ToolCall,
    *,
    durable: bool,
) -> ContextInheritanceMode:
    allowed = {"objective", "delegation_reason"}
    if durable:
        allowed.add("context_mode")
    unknown = set(tool_call.arguments) - allowed
    if unknown:
        raise ToolArgumentError(
            f"agent.research contains unsupported arguments: {', '.join(sorted(unknown))}"
        )
    raw = tool_call.arguments.get("context_mode", ContextInheritanceMode.FRESH.value)
    if not isinstance(raw, str):
        raise ToolArgumentError("agent.research context_mode must be a string")
    try:
        return ContextInheritanceMode(raw)
    except ValueError as exc:
        raise ToolArgumentError(
            "agent.research context_mode must be fresh, capsule, fork_tail, or resume"
        ) from exc


def delegate_durable_research(
    tool_call: ToolCall,
    *,
    objective: str,
    delegation_reason: str,
    context_mode: ContextInheritanceMode,
    context_source: ContextMaterialization | None,
    workspace_root: Path,
    delegation_store: object,
    parent_task_id: object | None,
    parent_binding: object | None,
) -> ToolResult:
    from agent_core.application.session_bootstrap import (
        SessionBootstrapCommand,
        SessionBootstrapService,
    )
    from agent_core.application.workspace_projection import rebuild_workspace
    from agent_core.domain.agent_capabilities import capability_set
    from agent_core.domain.subagent_delegation import (
        SubagentDelegationRequest,
        derive_child_binding,
    )
    from agent_core.domain.subagents import SubagentRole
    from agent_core.domain.task_bindings import TaskBindingSnapshot
    from agent_core.domain.tool_profiles import ToolProfile
    from agent_core.ports.task_admission_transaction import TaskAdmissionRequest

    child_capabilities = frozenset(capability_set(["agent.execute", "evidence.read"]))
    if not isinstance(parent_binding, TaskBindingSnapshot):
        return _refused(
            tool_call,
            reason="durable_delegation_requires_parent_binding",
            detail="no admission-frozen Task binding is available for this parent",
        )
    try:
        parent_uuid = (
            parent_task_id
            if isinstance(parent_task_id, UUID)
            else UUID(str(parent_task_id))
            if parent_task_id
            else None
        )
    except ValueError:
        parent_uuid = None
    if parent_uuid is None:
        return _refused(
            tool_call,
            reason="durable_delegation_requires_parent_task_id",
            detail="the parent Task identity is unavailable",
        )
    get_link = getattr(delegation_store, "get_link", None)
    if callable(get_link) and get_link(TaskId(parent_uuid)) is not None:
        return _refused(
            tool_call,
            reason="durable_delegation_depth_limit",
            detail="durable children cannot delegate (depth limit 1)",
        )
    try:
        delegated_context = (
            delegated_context_from_materialization(
                _require_context_source(context_source, context_mode),
                context_mode,
                created_at=tool_call.created_at,
            )
            if context_mode is not ContextInheritanceMode.FRESH
            else None
        )
        request = SubagentDelegationRequest(
            parent_task_id=TaskId(parent_uuid),
            parent_attempt_number=1,
            parent_tool_call_id=str(tool_call.tool_call_id),
            delegation_index=0,
            role=SubagentRole.RESEARCHER,
            objective=objective,
            context_mode=context_mode,
            requested_capabilities=child_capabilities,
            child_definition_snapshot_digest="0" * 64,
            child_capability_profile_ref="profile/researcher@1",
            expected_parent_binding_digest=parent_binding.binding_digest,
        )
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title=f"Research: {objective[:120]}",
                user_input=objective,
                workspace_root=Path(str(workspace_root)),
                policy_profile="read_only",
                tool_profile=ToolProfile.RESEARCH,
                network_profile="none",
                delegated_context=delegated_context,
            )
        )
        child_binding = derive_child_binding(
            parent_binding,
            request,
            child_task_id=TaskId(bootstrap.session.session_id),
            child_definition_ceiling=child_capabilities,
            zebra_child_policy_capabilities=child_capabilities,
        )
        child_admission = TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=child_binding,
        )
    except ValueError as exc:
        return _refused(
            tool_call,
            reason="delegation_derivation_failed",
            detail=str(exc)[:1000],
        )
    from agent_storage.postgres.subagent_delegation import (
        PostgresSubagentDelegationStore,
    )

    if not isinstance(delegation_store, PostgresSubagentDelegationStore):
        return _refused(
            tool_call,
            reason="durable_delegation_store_invalid",
            detail="durable delegation requires the PostgreSQL authority store",
        )
    receipt = delegation_store.delegate(request, child_admission)
    payload = {
        "delegation_reason": delegation_reason.strip(),
        "child_task_id": str(receipt.child_task_id),
        "context_mode": context_mode.value,
        "context_checksum": None if delegated_context is None else delegated_context.checksum,
        "status": "materialized",
        "resume": "durable_wakeup",
        "replayed": receipt.status == "replayed",
    }
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        metadata={
            **payload,
            "subagent_status": "materialized",
            "durable_delegation": True,
            "suspend_after_turn": True,
        },
    )


def _require_context_source(
    source: ContextMaterialization | None,
    mode: ContextInheritanceMode,
) -> ContextMaterialization:
    if source is None:
        raise ValueError(f"{mode.value} context_mode requires parent materialization")
    return source


def _refused(tool_call: ToolCall, *, reason: str, detail: str) -> ToolResult:
    payload = {"reason": reason, "detail": detail[:1000], "status": "failed"}
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        metadata={"reason": reason, "detail": detail[:1000]},
    )
