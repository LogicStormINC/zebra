"""CA-P7-02A: orchestration tools are Agent Layer calls over the runtime port."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_orchestration.application.orchestration_port import (
    OrchestrationToolError,
    PlanProposalReceipt,
    TaskRequestReceipt,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation
from agent_tools.builtin.orchestration import (
    PlanProposeTool,
    TaskRequestTool,
    plan_propose_contract,
    task_request_contract,
)


def _call(name: str, arguments: dict) -> ToolCall:
    return ToolCall(
        tool_call_id=uuid4(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )


VALID_PROPOSAL = {
    "_parent_task_id": str(uuid4()),
    "_parent_binding_digest": "a" * 64,
    "_budget_tokens": 1000,
    "_budget_tool_calls": 20,
    "_budget_seconds": 600,
    "_parent_capabilities": ["agent.execute", "evidence.read"],
    "_write_capabilities": [],
    "objective": "Analyze quarterly reports",
    "nodes": [
        {
            "node_key": "collect",
            "objective": "Collect sources",
            "preferred_agent_role": "researcher",
            "required_capabilities": ["evidence.read"],
            "max_model_tokens": 100,
            "max_tool_calls": 3,
            "max_runtime_seconds": 60,
        }
    ],
    "dependencies": [],
    "synthesis_instruction": "Merge",
}


class RecordingRuntime:
    """Test double capturing port calls; typed failures on demand."""

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail_with = fail_with

    def propose_plan(self, proposal, **context) -> PlanProposalReceipt:
        self.calls.append(("propose", (proposal, context)))
        if self.fail_with:
            raise OrchestrationToolError(self.fail_with, "typed failure")
        return PlanProposalReceipt(
            run_ref="run-1",
            plan_revision=1,
            node_keys=("collect",),
            reserved_budget=BudgetReservation(model_tokens=100, tool_calls=3, runtime_seconds=60),
        )

    def request_task(self, *, run_ref: str, node_key: str) -> TaskRequestReceipt:
        self.calls.append(("request", (run_ref, node_key)))
        if self.fail_with:
            raise OrchestrationToolError(self.fail_with, "typed failure")
        return TaskRequestReceipt(run_ref=run_ref, node_key=node_key, child_task_id=str(uuid4()))


class TestContracts:
    def test_names_follow_capability_vocabulary(self) -> None:
        assert plan_propose_contract.name == "orchestration.plan.propose"
        assert task_request_contract.name == "orchestration.task.request"

    def test_contracts_are_write_risk_with_required_arguments(self) -> None:
        for contract in (plan_propose_contract, task_request_contract):
            assert contract.required_arguments
            assert contract.execution_location.value == "zebra"


class TestPlanPropose:
    def test_valid_proposal_returns_run_coordinates(self) -> None:
        runtime = RecordingRuntime()
        result = PlanProposeTool(runtime).handle(  # type: ignore[arg-type]
            _call("orchestration.plan.propose", dict(VALID_PROPOSAL))
        )
        assert result.status is ToolCallStatus.EXECUTED
        payload = json.loads(result.output)
        assert payload["runRef"] == "run-1"
        assert payload["planRevision"] == 1
        assert payload["nodeKeys"] == ["collect"]
        assert payload["reservedBudget"]["modelTokens"] == 100

    def test_model_cannot_supply_authority_context(self) -> None:
        runtime = RecordingRuntime()
        PlanProposeTool(runtime).handle(  # type: ignore[arg-type]
            _call("orchestration.plan.propose", dict(VALID_PROPOSAL))
        )
        kind, (proposal, context) = runtime.calls[0]
        assert kind == "propose"
        assert proposal.nodes[0].node_key == "collect"
        assert context == {}

    def test_typed_runtime_failure_maps_to_typed_tool_failure(self) -> None:
        runtime = RecordingRuntime(fail_with="budget_beyond_parent")
        result = PlanProposeTool(runtime).handle(  # type: ignore[arg-type]
            _call("orchestration.plan.propose", dict(VALID_PROPOSAL))
        )
        assert result.status is ToolCallStatus.FAILED
        assert json.loads(result.output)["reason"] == "budget_beyond_parent"

    def test_structurally_invalid_proposal_is_rejected_without_runtime_call(self) -> None:
        runtime = RecordingRuntime()
        broken = {**VALID_PROPOSAL, "nodes": []}
        result = PlanProposeTool(runtime).handle(  # type: ignore[arg-type]
            _call("orchestration.plan.propose", broken)
        )
        assert result.status is ToolCallStatus.FAILED
        assert json.loads(result.output)["reason"] == "invalid_proposal"
        assert runtime.calls == []

    def test_without_runtime_fails_closed(self) -> None:
        result = PlanProposeTool().handle(_call("orchestration.plan.propose", dict(VALID_PROPOSAL)))
        assert result.status is ToolCallStatus.FAILED
        assert json.loads(result.output)["reason"] == "orchestration_requires_runtime"


class TestTaskRequest:
    def test_dispatch_returns_child_task_coordinates(self) -> None:
        runtime = RecordingRuntime()
        result = TaskRequestTool(runtime).handle(  # type: ignore[arg-type]
            _call("orchestration.task.request", {"run_ref": "run-1", "node_key": "collect"})
        )
        assert result.status is ToolCallStatus.EXECUTED
        payload = json.loads(result.output)
        assert payload["runRef"] == "run-1"
        assert payload["nodeKey"] == "collect"
        assert len(payload["childTaskId"]) == 36

    def test_without_runtime_fails_closed(self) -> None:
        result = TaskRequestTool().handle(
            _call("orchestration.task.request", {"run_ref": "r", "node_key": "n"})
        )
        assert result.status is ToolCallStatus.FAILED
        assert json.loads(result.output)["reason"] == "orchestration_requires_runtime"
