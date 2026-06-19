from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime.workspace import LocalWorkspace
from agent_tools import FileReadTool, ToolExecutor, ToolRegistry
from agent_tools.errors import ToolArgumentError


def _tool_call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments=arguments,
        created_at=datetime(2026, 6, 19, 15, 30, tzinfo=UTC),
    )


def test_file_read_tool_reads_file_within_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "todo.txt").write_text("hello workspace", encoding="utf-8")

    registry = ToolRegistry()
    reader = FileReadTool(workspace)
    registry.register(reader.contract, reader.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call({"path": "notes/todo.txt"}))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == "hello workspace"
    assert result.metadata == {
        "path": "notes/todo.txt",
        "byte_count": 15,
        "truncated": False,
    }


def test_file_read_tool_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    registry = ToolRegistry()
    reader = FileReadTool(workspace)
    registry.register(reader.contract, reader.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call({"path": "../secret.txt"}))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "path_outside_workspace"


def test_file_read_tool_truncates_large_output(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    (tmp_path / "large.txt").write_text("abcdefghij", encoding="utf-8")

    registry = ToolRegistry()
    reader = FileReadTool(workspace, max_bytes=4)
    registry.register(reader.contract, reader.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call({"path": "large.txt"}))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == "abcd"
    assert result.metadata == {
        "path": "large.txt",
        "byte_count": 10,
        "truncated": True,
    }


def test_file_read_tool_rejects_non_string_path_argument(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    registry = ToolRegistry()
    reader = FileReadTool(workspace)
    registry.register(reader.contract, reader.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="path' to be a string"):
        executor.execute(_tool_call({"path": 7}))
