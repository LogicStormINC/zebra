from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalRuntime
from agent_runtime.workspace import LocalWorkspace
from agent_tools import PatchApplyTool, ToolExecutor, ToolRegistry
from agent_tools.errors import ToolArgumentError


def _tool_call(patch_text: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="patch.apply",
        arguments={"patch": patch_text},
        created_at=datetime(2026, 6, 19, 17, 30, tzinfo=UTC),
    )


def test_patch_apply_tool_updates_file_within_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    patcher = PatchApplyTool(runtime, workspace)
    registry.register(patcher.contract, patcher.handle)
    executor = ToolExecutor(registry)
    target = tmp_path / "hello.txt"
    target.write_text("hello\n", encoding="utf-8")

    result = executor.execute(
        _tool_call(
            """--- hello.txt
+++ hello.txt
@@ -1 +1 @@
-hello
+world
"""
        )
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert target.read_text(encoding="utf-8") == "world\n"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["timed_out"] is False


def test_patch_apply_tool_strips_git_prefixes_for_new_files(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    patcher = PatchApplyTool(LocalRuntime(), workspace)

    result = patcher.handle(
        _tool_call(
            """--- /dev/null
+++ b/report.md
@@ -0,0 +1 @@
+ready
"""
        )
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "ready\n"
    assert not (tmp_path / "b" / "report.md").exists()


def test_patch_apply_tool_rejects_path_outside_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    patcher = PatchApplyTool(runtime, workspace)
    registry.register(patcher.contract, patcher.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="outside the workspace"):
        executor.execute(
            _tool_call(
                """--- ../secret.txt
+++ ../secret.txt
@@ -0,0 +1 @@
+secret
"""
            )
        )


def test_patch_apply_tool_returns_failed_result_on_patch_error(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    patcher = PatchApplyTool(runtime, workspace)
    registry.register(patcher.contract, patcher.handle)
    executor = ToolExecutor(registry)
    target = tmp_path / "hello.txt"
    target.write_text("hello\n", encoding="utf-8")

    result = executor.execute(
        _tool_call(
            """--- hello.txt
+++ hello.txt
@@ -1 +1 @@
-missing
+world
"""
        )
    )

    assert result.status is ToolCallStatus.FAILED
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert result.metadata["exit_code"] != 0


def test_patch_apply_tool_rejects_mismatched_hunk_counts_without_partial_write(
    tmp_path: Path,
) -> None:
    workspace = LocalWorkspace(tmp_path)
    patcher = PatchApplyTool(LocalRuntime(), workspace)

    result = patcher.handle(
        _tool_call(
            """--- /dev/null
+++ b/result.json
@@ -0,0 +1,2 @@
+{
+  "ok": true
+}
"""
        )
    )

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["failure_reason"] == "invalid_hunk_counts"
    assert not (tmp_path / "result.json").exists()
