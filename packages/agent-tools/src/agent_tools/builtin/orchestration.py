"""Orchestration tools: the Orchestrator AgentDefinition's Agent Layer calls (CA-P7-02A).

Both tools are ordinary ZEBRA-side tools whose handlers require the caller to
provide the orchestration runtime port — they hold no storage access of their
own. Without a runtime (unit harnesses, non-orchestrator sessions) the tools
fail closed with a typed reason, exactly like agent.plan outside the Harness.
"""

from __future__ import annotations

import json
from typing import Any

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult, ToolRisk
from agent_orchestration.application.orchestration_port import (
    OrchestrationRuntimePort,
    OrchestrationToolError,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation

from agent_tools.contracts import ToolContract

ORCHESTRATION_NODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "node_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "objective": {"type": "string", "minLength": 1, "maxLength": 2048},
        "preferred_agent_role": {"type": "string", "minLength": 1, "maxLength": 128},
        "required_capabilities": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 128},
            "maxItems": 32,
            "uniqueItems": True,
        },
        "isolation_mode": {
            "type": "string",
            "enum": ["shared_readonly", "worktree", "snapshot", "none"],
        },
        "max_model_tokens": {"type": "integer", "minimum": 0},
        "max_model_calls": {"type": "integer", "minimum": 0},
        "max_tool_calls": {"type": "integer", "minimum": 0},
        "max_runtime_seconds": {"type": "integer", "minimum": 0},
        "failure_policy": {
            "type": "string",
            "enum": ["fail_plan", "continue", "retry_once", "require_human"],
        },
    },
    "required": ["node_key", "objective", "preferred_agent_role", "required_capabilities"],
    "additionalProperties": False,
}

plan_propose_contract = ToolContract(
    name="orchestration.plan.propose",
    description=(
        "Propose one orchestration plan for this run. The runtime validates the "
        "proposal against the parent's capabilities, resources and remaining "
        "budget, then freezes it as revision 1 of a new run. Rejected proposals "
        "return a typed reason and change nothing."
    ),
    argument_properties={
        "objective": {"type": "string", "minLength": 1, "maxLength": 2048},
        "nodes": {
            "type": "array",
            "items": ORCHESTRATION_NODE_SCHEMA,
            "minItems": 1,
            "maxItems": 32,
        },
        "dependencies": {
            "type": "array",
            "maxItems": 256,
            "items": {
                "type": "object",
                "properties": {
                    "from_node": {"type": "string", "minLength": 1, "maxLength": 128},
                    "to_node": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                "required": ["from_node", "to_node"],
                "additionalProperties": False,
            },
        },
        "max_parallelism": {"type": "integer", "minimum": 1, "maximum": 32},
        "completion_strategy": {
            "type": "string",
            "enum": ["all_success", "all_terminal", "any_success"],
        },
        "synthesis_instruction": {"type": "string", "minLength": 1, "maxLength": 2048},
    },
    required_arguments=("objective", "nodes", "synthesis_instruction"),
    risk=ToolRisk.WRITE,
    timeout_seconds=30,
)

task_request_contract = ToolContract(
    name="orchestration.task.request",
    description=(
        "Request dispatch of one ready node of an existing orchestration run. "
        "The runtime owns scheduling and admission; this call only names the "
        "node and returns its child task coordinates when dispatch succeeds."
    ),
    argument_properties={
        "run_ref": {"type": "string", "minLength": 1, "maxLength": 128},
        "node_key": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    required_arguments=("run_ref", "node_key"),
    risk=ToolRisk.WRITE,
    timeout_seconds=30,
)


def _failed(tool_call: ToolCall, reason: str, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output=json.dumps({"reason": reason, "detail": detail[:512]}),
        metadata={"reason": reason},
    )


def _succeeded(tool_call: ToolCall, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output=json.dumps(payload),
    )


class PlanProposeTool:
    """orchestration.plan.propose — validate and freeze via the runtime port."""

    def __init__(self, runtime: OrchestrationRuntimePort | None = None) -> None:
        self._runtime = runtime

    @property
    def contract(self) -> ToolContract:
        return plan_propose_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        runtime = self._runtime
        if runtime is None:
            return _failed(
                tool_call,
                "orchestration_requires_runtime",
                "orchestration tools may only execute inside an orchestration-capable session",
            )
        try:
            receipt = runtime.propose_plan(
                _proposal_from_arguments(tool_call.arguments),
                parent_task_id=str(tool_call.arguments.get("_parent_task_id", "")),
                parent_binding_digest=str(tool_call.arguments.get("_parent_binding_digest", "")),
                parent_remaining_budget=BudgetReservation(
                    model_tokens=int(tool_call.arguments.get("_budget_tokens", 0)),
                    tool_calls=int(tool_call.arguments.get("_budget_tool_calls", 0)),
                    runtime_seconds=int(tool_call.arguments.get("_budget_seconds", 0)),
                ),
                parent_capabilities=frozenset(
                    str(item) for item in tool_call.arguments.get("_parent_capabilities", [])
                ),
                write_capabilities=frozenset(
                    str(item) for item in tool_call.arguments.get("_write_capabilities", [])
                ),
            )
        except OrchestrationToolError as error:
            return _failed(tool_call, error.reason_code, error.detail)
        except (ValueError, TypeError):
            return _failed(tool_call, "invalid_proposal", "proposal failed domain validation")
        return _succeeded(
            tool_call,
            {
                "runRef": receipt.run_ref,
                "planRevision": receipt.plan_revision,
                "nodeKeys": list(receipt.node_keys),
                "reservedBudget": {
                    "modelTokens": receipt.reserved_budget.model_tokens,
                    "toolCalls": receipt.reserved_budget.tool_calls,
                    "runtimeSeconds": receipt.reserved_budget.runtime_seconds,
                },
            },
        )


class TaskRequestTool:
    """orchestration.task.request — dispatch one ready node via the runtime port."""

    def __init__(self, runtime: OrchestrationRuntimePort | None = None) -> None:
        self._runtime = runtime

    @property
    def contract(self) -> ToolContract:
        return task_request_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        runtime = self._runtime
        if runtime is None:
            return _failed(
                tool_call,
                "orchestration_requires_runtime",
                "orchestration tools may only execute inside an orchestration-capable session",
            )
        try:
            receipt = runtime.request_task(
                run_ref=str(tool_call.arguments.get("run_ref", "")),
                node_key=str(tool_call.arguments.get("node_key", "")),
            )
        except OrchestrationToolError as error:
            return _failed(tool_call, error.reason_code, error.detail)
        return _succeeded(
            tool_call,
            {
                "runRef": receipt.run_ref,
                "nodeKey": receipt.node_key,
                "childTaskId": receipt.child_task_id,
            },
        )


def _proposal_from_arguments(arguments: dict[str, Any]) -> Any:
    from agent_orchestration.domain.orchestration import (
        OrchestrationPlanProposal,
    )

    return OrchestrationPlanProposal.model_validate(
        {
            "objective": arguments.get("objective"),
            "nodes": [
                {
                    **node,
                    "required_capabilities": list(node.get("required_capabilities", [])),
                    "max_model_calls": node.get("max_model_calls", 0),
                }
                for node in arguments.get("nodes", [])
            ],
            "dependencies": [
                {"from_node": dep["from_node"], "to_node": dep["to_node"]}
                for dep in arguments.get("dependencies", [])
            ],
            "max_parallelism": arguments.get("max_parallelism", 1),
            "completion_strategy": arguments.get("completion_strategy", "all_success"),
            "synthesis_instruction": arguments.get("synthesis_instruction"),
        }
    )
