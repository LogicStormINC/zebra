import sys
from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalRuntime
from agent_runtime.workspace import LocalWorkspace
from agent_tools import FileReadTool, PatchApplyTool, TestsRunTool, ToolExecutor, ToolRegistry


def _tool_call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 6, 19, 18, 30, tzinfo=UTC),
    )


def test_local_toolchain_can_read_patch_and_validate(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()

    reader = FileReadTool(workspace)
    patcher = PatchApplyTool(runtime, workspace)
    validator = TestsRunTool(
        runtime,
        workspace,
        presets={
            "smoke": (
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "text = Path('hello.txt').read_text(encoding='utf-8'); "
                "assert text == 'world\\n'; "
                "print('validated')",
            )
        },
    )
    registry.register(reader.contract, reader.handle)
    registry.register(patcher.contract, patcher.handle)
    registry.register(validator.contract, validator.handle)
    executor = ToolExecutor(registry)

    target = tmp_path / "hello.txt"
    target.write_text("hello\n", encoding="utf-8")

    read_result = executor.execute(_tool_call("files.read", {"path": "hello.txt"}))
    patch_result = executor.execute(
        _tool_call(
            "patch.apply",
            {
                "patch": """--- hello.txt
+++ hello.txt
@@ -1 +1 @@
-hello
+world
"""
            },
        )
    )
    validation_result = executor.execute(_tool_call("tests.run", {"preset": "smoke"}))

    assert read_result.status is ToolCallStatus.EXECUTED
    assert read_result.output == "hello\n"
    assert patch_result.status is ToolCallStatus.EXECUTED
    assert validation_result.status is ToolCallStatus.EXECUTED
    assert validation_result.output.strip() == "validated"
    assert target.read_text(encoding="utf-8") == "world\n"
