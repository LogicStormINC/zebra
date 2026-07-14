from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import (
    SubagentId,
    new_message_id,
    new_subagent_id,
    new_tool_call_id,
)
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.subagents import (
    ResearchSubagentResult,
    ResearchSubagentTask,
    SubagentStatus,
)
from agent_core.domain.tools import ToolCall
from agent_runtime import (
    LocalResearchSubagentCoordinator,
    LocalResearchSubagentRunner,
    ReadOnlyToolGateway,
    SubagentLimitError,
)

NOW = datetime(2026, 7, 14, 14, 0, tzinfo=UTC)


def test_coordinator_enforces_child_and_depth_limits(tmp_path) -> None:
    coordinator = LocalResearchSubagentCoordinator(_completed_runner, max_children=1)
    task = _task(tmp_path)
    first = coordinator.spawn(task)

    assert coordinator.join(first).status is SubagentStatus.COMPLETED
    with pytest.raises(SubagentLimitError, match="child limit"):
        coordinator.spawn(task)
    coordinator.close()

    depth_limited = LocalResearchSubagentCoordinator(_completed_runner, max_depth=1)
    with pytest.raises(SubagentLimitError, match="depth limit"):
        depth_limited.spawn(_task(tmp_path, depth=2))
    depth_limited.close()

    budget_limited = LocalResearchSubagentCoordinator(_completed_runner)
    with pytest.raises(SubagentLimitError, match="model-call limit"):
        budget_limited.spawn(
            ResearchSubagentTask(
                objective="Inspect evidence.",
                workspace_root=tmp_path.resolve(),
                max_model_calls=4,
            )
        )
    with pytest.raises(SubagentLimitError, match="tool-call limit"):
        budget_limited.spawn(
            ResearchSubagentTask(
                objective="Inspect evidence.",
                workspace_root=tmp_path.resolve(),
                max_tool_calls=3,
            )
        )
    budget_limited.close()


def test_running_child_cancellation_converges_without_orphan(tmp_path) -> None:
    started = Event()

    def blocking_runner(
        subagent_id: SubagentId,
        task: ResearchSubagentTask,
        cancellation: Event,
    ) -> ResearchSubagentResult:
        started.set()
        cancellation.wait(timeout=2)
        return _completed_result(subagent_id)

    coordinator = LocalResearchSubagentCoordinator(blocking_runner)
    subagent_id = coordinator.spawn(_task(tmp_path))
    assert started.wait(timeout=1)
    assert coordinator.collect(subagent_id) is None

    assert coordinator.cancel(subagent_id) is True
    assert coordinator.join(subagent_id).status is SubagentStatus.CANCELLED
    assert coordinator.cancel(subagent_id) is False
    coordinator.close()

    parent_closed = Event()

    def parent_owned_runner(
        subagent_id: SubagentId,
        task: ResearchSubagentTask,
        cancellation: Event,
    ) -> ResearchSubagentResult:
        parent_closed.set()
        cancellation.wait(timeout=2)
        return _completed_result(subagent_id)

    parent = LocalResearchSubagentCoordinator(parent_owned_runner)
    child_id = parent.spawn(_task(tmp_path))
    assert parent_closed.wait(timeout=1)
    parent.close()
    assert parent.join(child_id).status is SubagentStatus.CANCELLED


def test_child_gateway_exposes_only_readonly_non_recursive_tools(tmp_path) -> None:
    gateway = ReadOnlyToolGateway(tmp_path.resolve())

    assert tuple(tool.name for tool in gateway.model_tools) == (
        "files.read",
        "git.status",
    )
    assert "agent.research" not in {tool.name for tool in gateway.model_tools}


def test_child_write_request_is_denied_before_execution(tmp_path) -> None:
    write_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="patch.apply",
        arguments={
            "patch": (
                "*** Begin Patch\n*** Add File: pwned.txt\n+blocked\n*** End Patch"
            )
        },
        created_at=NOW,
        provider_call_id="write_call",
    )
    gateway = ScriptedModelGateway(
        responses=(ScriptedModelResponse(completion=_completion("Write it.", write_call)),)
    )
    runner = LocalResearchSubagentRunner(gateway)
    subagent_id = new_subagent_id()

    result = runner(subagent_id, _task(tmp_path), Event())

    assert result.status is SubagentStatus.FAILED
    assert result.tool_calls_used == 0
    assert tuple(tool.name for tool in gateway.tool_requests[0]) == (
        "files.read",
        "git.status",
    )
    assert not (tmp_path / "pwned.txt").exists()


def _task(tmp_path: Path, *, depth: int = 1) -> ResearchSubagentTask:
    return ResearchSubagentTask(
        objective="Inspect evidence.",
        workspace_root=tmp_path.resolve(),
        depth=depth,
    )


def _completed_runner(
    subagent_id: SubagentId,
    task: ResearchSubagentTask,
    cancellation: Event,
) -> ResearchSubagentResult:
    return _completed_result(subagent_id)


def _completed_result(subagent_id: SubagentId) -> ResearchSubagentResult:
    return ResearchSubagentResult(
        subagent_id=subagent_id,
        status=SubagentStatus.COMPLETED,
        summary="Evidence found.",
        confidence=0.5,
    )


def _completion(content: str, tool_call: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=(tool_call,),
    )
