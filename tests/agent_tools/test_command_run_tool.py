import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalRuntime
from agent_runtime.workspace import LocalWorkspace
from agent_tools import CommandRunTool, ToolExecutor, ToolRegistry
from agent_tools.errors import ToolArgumentError


def _tool_call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments=arguments,
        created_at=datetime(2026, 6, 19, 16, 30, tzinfo=UTC),
    )


def test_command_run_tool_executes_typed_command_in_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call(
            {
                "command": (
                    sys.executable,
                    "-c",
                    "import pathlib; print(pathlib.Path.cwd().name)",
                ),
            }
        )
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output.strip() == tmp_path.name
    assert result.metadata == {
        "command": [sys.executable, "-c", "import pathlib; print(pathlib.Path.cwd().name)"],
        "cwd": ".",
        "exit_code": 0,
        "stderr": "",
        "timed_out": False,
    }


def test_command_run_tool_captures_non_zero_exit(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call(
            {
                "command": (
                    sys.executable,
                    "-c",
                    "import sys; print('boom'); print('bad', file=sys.stderr); sys.exit(7)",
                ),
            }
        )
    )

    assert result.status is ToolCallStatus.FAILED
    assert result.output.strip() == "boom"
    assert result.metadata["exit_code"] == 7
    assert result.metadata["stderr"].strip() == "bad"
    assert result.metadata["timed_out"] is False


def test_command_run_tool_propagates_timeout(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call(
            {
                "command": (
                    sys.executable,
                    "-c",
                    "import time; print('start'); time.sleep(0.2)",
                ),
                "timeout_seconds": 0.05,
            }
        )
    )

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["exit_code"] is None
    assert result.metadata["timed_out"] is True


def test_command_run_tool_rejects_shell_string_arguments(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="list or tuple of strings"):
        executor.execute(_tool_call({"command": "python -c 'print(1)'"}))


def test_command_run_tool_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="must stay within the workspace"):
        executor.execute(
            _tool_call(
                {
                    "command": (sys.executable, "-c", "print('ok')"),
                    "cwd": "../outside",
                }
            )
        )
