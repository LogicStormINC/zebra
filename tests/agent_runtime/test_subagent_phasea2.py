"""Phase A slice 2: runtime injection, spawn callback, child toolset."""

from __future__ import annotations

from pathlib import Path

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.research import ReadOnlyToolGateway
from agent_runtime.subagents import LocalResearchSubagentCoordinator


class RecordingRuntime(LocalRuntime):
    """Marker runtime proving children reuse the parent instance."""

    def __init__(self) -> None:
        super().__init__()
        self.instances: list[ReadOnlyToolGateway] = []


class ScriptedRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, subagent_id, task, cancellation):  # noqa: ANN001

        from agent_core.domain.subagents import (
            ResearchSubagentResult,
            SubagentStatus,
        )

        self.calls += 1
        return ResearchSubagentResult(
            subagent_id=subagent_id,
            status=SubagentStatus.COMPLETED,
            summary="done",
        )


def test_child_gateway_uses_injected_runtime(tmp_path: Path) -> None:
    runtime = RecordingRuntime()
    gateway = ReadOnlyToolGateway(tmp_path, runtime=runtime)
    tools = {tool.name for tool in gateway.model_tools}
    assert tools == {"files.read", "files.search", "git.status"}
    assert "agent.research" not in tools


def test_child_gateway_falls_back_to_local_runtime(tmp_path: Path) -> None:
    gateway = ReadOnlyToolGateway(tmp_path)
    assert any(tool.name == "git.status" for tool in gateway.model_tools)


def test_spawn_callback_fires_immediately(tmp_path: Path) -> None:
    spawned: list[tuple[str, str]] = []

    def on_spawned(subagent_id, task) -> None:
        spawned.append((str(subagent_id), task.objective))

    coordinator = LocalResearchSubagentCoordinator(
        ScriptedRunner(),
        on_spawned=on_spawned,
    )
    try:
        from agent_core.domain.subagents import ResearchSubagentTask

        coordinator.spawn(
            ResearchSubagentTask(
                objective="Realtime start",
                workspace_root=tmp_path.resolve(),
            )
        )
        assert len(spawned) == 1
        assert spawned[0][1] == "Realtime start"
    finally:
        coordinator.close()
