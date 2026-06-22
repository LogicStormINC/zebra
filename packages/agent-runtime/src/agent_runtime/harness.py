from __future__ import annotations

from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness.models import HarnessLoopResult
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_tools import (
    CommandRunTool,
    FileReadTool,
    GitStatusTool,
    PatchApplyTool,
    TestsRunTool,
    ToolExecutor,
    ToolRegistry,
)
from agent_tools.errors import ToolRegistryError

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.workspace import LocalWorkspace

DEFAULT_TEST_PRESETS = {
    "pytest": ("uv", "run", "pytest"),
    "check": ("make", "check"),
    "test": ("make", "test"),
}


def run_local_harness(
    *,
    prompt: str,
    title: str,
    workspace_root: Path,
    model_gateway: ModelGatewayPort,
    policy_profile: PolicyProfile = PolicyProfile.WORKSPACE_WRITE,
) -> HarnessLoopResult:
    return HarnessLoop().run(
        HarnessTask(
            title=title,
            user_input=prompt,
            max_attempts=1,
            max_model_calls=1,
            max_tool_calls=1,
            workspace_root=workspace_root,
        ),
        SingleAttemptOrchestrator(
            model_gateway,
            LocalPolicyEngine(profile=policy_profile),
            LocalToolGateway(workspace_root),
        ).run,
    )


class LocalToolGateway(ToolGatewayPort):
    def __init__(self, workspace_root: Path) -> None:
        self._workspace = LocalWorkspace(workspace_root)
        self._workspace.ensure()
        runtime = LocalRuntime()
        registry = ToolRegistry()
        tools = (
            FileReadTool(self._workspace),
            GitStatusTool(runtime, self._workspace),
            PatchApplyTool(runtime, self._workspace),
            TestsRunTool(runtime, self._workspace, DEFAULT_TEST_PRESETS),
            CommandRunTool(runtime, self._workspace),
        )
        for tool in tools:
            registry.register(tool.contract, tool.handle)
        self._executor = ToolExecutor(registry)

    def execute(self, tool_call: ToolCall) -> ToolResult:
        try:
            return self._executor.execute(tool_call)
        except ToolRegistryError as exc:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output="",
                metadata={
                    "reason": "tool_validation_error",
                    "detail": str(exc),
                },
            )
