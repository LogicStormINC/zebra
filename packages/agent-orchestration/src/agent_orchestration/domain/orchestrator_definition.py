"""The system Orchestrator AgentDefinition (ORCH-AGENT-DEF-01, plan 6.1-6.3).

`system/orchestrator@1` is an ORDINARY definition: it flows through
AgentDefinitionVersion → Release → Snapshot → TaskBinding like any other
agent and holds no bypass privileges. Its ceiling is the eight
`orchestration.*` capabilities; the forbidden list can never be granted by
accident. Every orchestration tool is an Agent Layer application call —
none touches storage directly.
"""

from __future__ import annotations

from typing import Final

from agent_core.domain.agent_capabilities import capability_set
from agent_tools.contracts import ToolContract, ToolRisk

ORCHESTRATOR_DEFINITION_REF: Final = "system/orchestrator@1"
ORCHESTRATOR_CAPABILITY_PROFILE_REF: Final = "profile/orchestrator@1"

ORCHESTRATOR_ALLOWED_CAPABILITIES: Final = capability_set(
    [
        "orchestration.plan.propose",
        "orchestration.plan.read",
        "orchestration.task.request",
        "orchestration.task.read",
        "orchestration.task.cancel",
        "orchestration.result.read",
        "orchestration.result.synthesize",
        "orchestration.replan.propose",
    ]
)

# Blocklist entries are literal names (some contain underscores) — they are
# never grantable capabilities, so they stay plain strings rather than
# Capability instances.
ORCHESTRATOR_FORBIDDEN_CAPABILITIES: Final = frozenset(
    {
        "host.business.write",
        "connector.modify",
        "authority.issue",
        "agent_definition.publish",
        "worker.assign",
        "lease.override",
        "effect.force_retry",
        "workspace.force_merge",
    }
)

_PLAN_SUBMIT = ToolContract(
    name="orchestration.plan.submit",
    description="Submit one structured OrchestrationPlanProposal for validation.",
    required_arguments=("proposal",),
    argument_properties={
        "proposal": {
            "type": "string",
            "description": "zebra.orchestration-plan/1 JSON proposal",
        },
    },
    scopes=("orchestration.plan.propose",),
    risk=ToolRisk.WRITE,
)

_PLAN_INSPECT = ToolContract(
    name="orchestration.plan.inspect",
    description="Read the current validated plan snapshot and its digest.",
    required_arguments=("run_id",),
    argument_properties={"run_id": {"type": "string"}},
    scopes=("orchestration.plan.read",),
)

_TASK_SPAWN = ToolContract(
    name="orchestration.task.spawn",
    description="Request materialization of one plan node as a child Task.",
    required_arguments=("run_id", "node_key"),
    argument_properties={
        "run_id": {"type": "string"},
        "node_key": {"type": "string"},
    },
    scopes=("orchestration.task.request",),
    risk=ToolRisk.WRITE,
)

_TASK_LIST = ToolContract(
    name="orchestration.task.list",
    description="List nodes with statuses and child task references.",
    required_arguments=("run_id",),
    argument_properties={"run_id": {"type": "string"}},
    scopes=("orchestration.task.read",),
)

_TASK_WAIT = ToolContract(
    name="orchestration.task.wait",
    description="Declare the parent waits for child completion (durable wakeup).",
    required_arguments=("run_id",),
    argument_properties={"run_id": {"type": "string"}},
    scopes=("orchestration.task.read",),
)

_TASK_CANCEL = ToolContract(
    name="orchestration.task.cancel",
    description="Cancel one node or the whole run through the Control Plane.",
    required_arguments=("run_id",),
    argument_properties={
        "run_id": {"type": "string"},
        "node_key": {"type": "string", "description": "optional; omit to cancel the run"},
    },
    scopes=("orchestration.task.cancel",),
    risk=ToolRisk.WRITE,
)

_RESULT_READ = ToolContract(
    name="orchestration.result.read",
    description="Read one child's result bundle by digest.",
    required_arguments=("child_task_id",),
    argument_properties={"child_task_id": {"type": "string"}},
    scopes=("orchestration.result.read",),
)

_REPLAN_SUBMIT = ToolContract(
    name="orchestration.replan.submit",
    description="Propose an append-only plan revision at a safe boundary.",
    required_arguments=("run_id", "revision"),
    argument_properties={
        "run_id": {"type": "string"},
        "revision": {"type": "string", "description": "added/cancelled node lists"},
    },
    scopes=("orchestration.replan.propose",),
    risk=ToolRisk.WRITE,
)

ORCHESTRATOR_TOOLS: Final = (
    _PLAN_SUBMIT,
    _PLAN_INSPECT,
    _TASK_SPAWN,
    _TASK_LIST,
    _TASK_WAIT,
    _TASK_CANCEL,
    _RESULT_READ,
    _REPLAN_SUBMIT,
)

ORCHESTRATOR_TOOL_NAMES: Final = frozenset(tool.name for tool in ORCHESTRATOR_TOOLS)

# Agent Team tools stay locked until Phase E (plan 6.3).
ORCHESTRATOR_TEAM_TOOLS_LOCKED: Final = (
    "orchestration.message.send",
    "orchestration.message.list",
    "orchestration.task.claim",
    "orchestration.task.release",
)


class OrchestratorDefinitionError(ValueError):
    """The orchestrator definition violates its own ceiling."""


def validate_orchestrator_definition() -> frozenset[str]:
    """Validate ceiling/tool consistency; return the allowed capability set.

    The orchestrator's tool surface may only require capabilities inside
    its ceiling, must never touch the forbidden list, and must expose
    exactly the eight plan-6.3 tools.
    """

    if ORCHESTRATOR_ALLOWED_CAPABILITIES & ORCHESTRATOR_FORBIDDEN_CAPABILITIES:
        raise OrchestratorDefinitionError("allowed and forbidden capabilities overlap")
    for capability in ORCHESTRATOR_ALLOWED_CAPABILITIES:
        if not capability.startswith("orchestration."):
            raise OrchestratorDefinitionError(
                f"orchestrator ceiling leaked a non-orchestration capability: {capability}"
            )
    for tool in ORCHESTRATOR_TOOLS:
        if not tool.name.startswith("orchestration."):
            raise OrchestratorDefinitionError(f"foreign tool in surface: {tool.name}")
        for scope in tool.scopes:
            if scope in ORCHESTRATOR_FORBIDDEN_CAPABILITIES:
                raise OrchestratorDefinitionError(
                    f"{tool.name} requires a forbidden capability: {scope}"
                )
            if scope not in ORCHESTRATOR_ALLOWED_CAPABILITIES:
                raise OrchestratorDefinitionError(
                    f"{tool.name} requires an uncapped capability: {scope}"
                )
    expected = {
        "orchestration.plan.submit",
        "orchestration.plan.inspect",
        "orchestration.task.spawn",
        "orchestration.task.list",
        "orchestration.task.wait",
        "orchestration.task.cancel",
        "orchestration.result.read",
        "orchestration.replan.submit",
    }
    if ORCHESTRATOR_TOOL_NAMES != expected:
        raise OrchestratorDefinitionError("tool surface does not match plan 6.3")
    return ORCHESTRATOR_ALLOWED_CAPABILITIES
