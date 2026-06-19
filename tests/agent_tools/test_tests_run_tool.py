import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalRuntime
from agent_runtime.workspace import LocalWorkspace
from agent_tools import TestsRunTool as ValidationRunner
from agent_tools import ToolExecutor, ToolRegistry
from agent_tools.errors import ToolArgumentError


def _tool_call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="tests.run",
        arguments=arguments,
        created_at=datetime(2026, 6, 19, 18, 10, tzinfo=UTC),
    )


def test_tests_run_tool_executes_defined_preset(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = ValidationRunner(
        runtime,
        workspace,
        presets={"smoke": (sys.executable, "-c", "print('tests-ok')")},
    )
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call({"preset": "smoke"}))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output.strip() == "tests-ok"
    assert result.metadata["preset"] == "smoke"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["timed_out"] is False


def test_tests_run_tool_returns_failed_result_for_non_zero_exit(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = ValidationRunner(
        runtime,
        workspace,
        presets={
            "fail": (
                sys.executable,
                "-c",
                "import sys; print('bad', file=sys.stderr); sys.exit(3)",
            )
        },
    )
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call({"preset": "fail"}))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["exit_code"] == 3
    assert result.metadata["stderr"].strip() == "bad"


def test_tests_run_tool_rejects_unknown_preset(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = ValidationRunner(
        runtime,
        workspace,
        presets={"smoke": (sys.executable, "-c", "print('ok')")},
    )
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="preset is not defined"):
        executor.execute(_tool_call({"preset": "missing"}))


def test_tests_run_tool_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = ValidationRunner(
        runtime,
        workspace,
        presets={"smoke": (sys.executable, "-c", "print('ok')")},
    )
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="must stay within the workspace"):
        executor.execute(_tool_call({"preset": "smoke", "cwd": "../outside"}))
