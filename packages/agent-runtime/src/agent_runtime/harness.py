from __future__ import annotations

from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness.models import HarnessLoopResult
from agent_core.ports.context_compiler import ConfirmedMemoryInput
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
    confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
) -> HarnessLoopResult:
    tool_gateway = LocalToolGateway(workspace_root)
    context_compiler = LocalContextCompiler()
    return HarnessLoop().run(
        HarnessTask(
            title=title,
            user_input=prompt,
            max_attempts=1,
            max_model_calls=4,
            max_tool_calls=3,
            workspace_root=workspace_root,
            confirmed_memories=confirmed_memories,
        ),
        SingleAttemptOrchestrator(
            model_gateway,
            LocalPolicyEngine(profile=policy_profile),
            tool_gateway,
            model_step=HarnessModelStep(
                context_compiler=context_compiler,
                available_tools=tool_gateway.model_tools,
                conversation_compactor=context_compiler,
            ),
            synthesize_tool_results=True,
            parallel_safe_tools=tool_gateway.parallel_safe_tools,
            max_parallel_tool_calls=3,
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
        self._model_tools = registry.model_tools()
        self._parallel_safe_tools = registry.parallel_safe_names()
        self._executor = ToolExecutor(registry)

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self._model_tools

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        return self._parallel_safe_tools

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
