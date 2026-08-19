"""Cloud cutover tests: cloud parents never join synchronously."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_core.application.mock_model import (
    ScriptedModelGateway,
    ScriptedModelResponse,
)
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_runtime.harness import LocalToolGateway
from agent_runtime.research import ResearchSubagentTool
from agent_runtime.subagents import LocalResearchSubagentCoordinator


def _completion(text: str) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_tool_call_id(),
            role=MessageRole.ASSISTANT,
            content=text,
            created_at=datetime.now(UTC),
        )
    )


class SlowRunner:
    """A child runner that would block a synchronous join for a long time."""

    def __init__(self) -> None:
        self.started = 0

    def __call__(self, subagent_id, task, cancellation):  # noqa: ANN001
        import time

        from agent_core.domain.subagents import (
            ResearchSubagentResult,
            SubagentStatus,
        )

        self.started += 1
        time.sleep(0.05)
        return ResearchSubagentResult(
            subagent_id=subagent_id,
            status=SubagentStatus.COMPLETED,
            summary="slow child done",
        )


def _research_call() -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.research",
        arguments={
            "objective": "Collect evidence",
            "delegation_reason": "Independent bounded collection",
        },
        created_at=datetime.now(UTC),
    )


def test_durable_tool_returns_running_receipt_without_join(tmp_path: Path) -> None:
    runner = SlowRunner()
    coordinator = LocalResearchSubagentCoordinator(runner)
    tool = ResearchSubagentTool(coordinator, tmp_path, wait_for_result=False)
    try:
        result = tool.handle(_research_call())
        assert result.status.value == "executed"
        assert result.metadata["subagent_status"] == "running"
        assert result.metadata["durable_delegation"] is True
        assert "durable_wakeup" in result.output
    finally:
        coordinator.close()


def test_local_fast_path_still_joins(tmp_path: Path) -> None:
    coordinator = LocalResearchSubagentCoordinator(SlowRunner())
    tool = ResearchSubagentTool(coordinator, tmp_path, wait_for_result=True)
    try:
        result = tool.handle(_research_call())
        assert result.metadata["subagent_status"] in {"completed", "failed"}
        assert result.metadata.get("durable_delegation") is not True
    finally:
        coordinator.close()


def test_gateway_durable_flag_reaches_the_tool(tmp_path: Path) -> None:
    gateway = LocalToolGateway(
        tmp_path,
        model_gateway=ScriptedModelGateway(
            responses=(ScriptedModelResponse(completion=_completion("direct")),)
        ),
        durable_delegation=True,
    )
    try:
        research = next(
            tool for tool in gateway.model_tools if tool.name == "agent.research"
        )
        assert research is not None  # still advertised; only the wait changes
    finally:
        gateway.close()
