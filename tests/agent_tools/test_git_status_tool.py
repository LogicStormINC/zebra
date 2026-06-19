from datetime import UTC, datetime
from pathlib import Path
from subprocess import run

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalRuntime
from agent_runtime.workspace import LocalWorkspace
from agent_tools import GitStatusTool, ToolExecutor, ToolRegistry
from agent_tools.errors import ToolArgumentError


def _tool_call(arguments: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="git.status",
        arguments=arguments or {},
        created_at=datetime(2026, 6, 19, 19, 0, tzinfo=UTC),
    )


def _init_repo(path: Path) -> None:
    run(("git", "init"), cwd=path, check=True, capture_output=True, text=True)
    run(
        ("git", "config", "user.name", "Zebra Agent"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    run(
        ("git", "config", "user.email", "zebra@example.com"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_status_tool_reports_clean_repository(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("hello\n", encoding="utf-8")
    run(("git", "add", "tracked.txt"), cwd=tmp_path, check=True, capture_output=True, text=True)
    run(("git", "commit", "-m", "init"), cwd=tmp_path, check=True, capture_output=True, text=True)

    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    status_tool = GitStatusTool(runtime, workspace)
    registry.register(status_tool.contract, status_tool.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call())

    assert result.status is ToolCallStatus.EXECUTED
    assert "##" in result.output
    assert "tracked.txt" not in result.output
    assert result.metadata["exit_code"] == 0


def test_git_status_tool_reports_dirty_repository(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("hello\n", encoding="utf-8")
    run(("git", "add", "tracked.txt"), cwd=tmp_path, check=True, capture_output=True, text=True)
    run(("git", "commit", "-m", "init"), cwd=tmp_path, check=True, capture_output=True, text=True)
    tracked.write_text("changed\n", encoding="utf-8")

    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    status_tool = GitStatusTool(runtime, workspace)
    registry.register(status_tool.contract, status_tool.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call())

    assert result.status is ToolCallStatus.EXECUTED
    assert "tracked.txt" in result.output
    assert result.metadata["exit_code"] == 0


def test_git_status_tool_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    status_tool = GitStatusTool(runtime, workspace)
    registry.register(status_tool.contract, status_tool.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="must stay within the workspace"):
        executor.execute(_tool_call({"cwd": "../outside"}))
