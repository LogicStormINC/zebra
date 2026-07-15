from __future__ import annotations

from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tool_profiles import ToolProfile, tool_names_for_profile
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness.models import HarnessLoopResult
from agent_core.ports.context_compiler import ConfirmedMemoryInput
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_security import DEFAULT_NETWORK_PROFILE, LocalPolicyEngine, NetworkProfile, PolicyProfile
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
from agent_runtime.research import LocalResearchSubagentRunner, ResearchSubagentTool
from agent_runtime.subagents import LocalResearchSubagentCoordinator
from agent_runtime.workspace import LocalWorkspace

DEFAULT_TEST_PRESETS = {
    "pytest": ("uv", "run", "pytest"),
    "check": ("make", "check"),
    "test": ("make", "test"),
}
DEFAULT_RESEARCH_CHILD_LIMIT = 3


def run_local_harness(
    *,
    prompt: str,
    title: str,
    workspace_root: Path,
    model_gateway: ModelGatewayPort,
    policy_profile: PolicyProfile = PolicyProfile.WORKSPACE_WRITE,
    tool_profile: ToolProfile = ToolProfile.GENERAL,
    network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE,
    confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
) -> HarnessLoopResult:
    tool_gateway = LocalToolGateway(
        workspace_root,
        model_gateway=model_gateway,
        tool_profile=tool_profile,
    )
    context_compiler = LocalContextCompiler()
    try:
        return HarnessLoop().run(
            HarnessTask(
                title=title,
                user_input=prompt,
                max_attempts=1,
                max_model_calls=4,
                max_tool_calls=3,
                workspace_root=workspace_root,
                policy_profile=policy_profile.value,
                tool_profile=tool_profile,
                network_profile=network_profile.name.value,
                network_allowlist=network_profile.domain_allowlist,
                confirmed_memories=confirmed_memories,
            ),
            SingleAttemptOrchestrator(
                model_gateway,
                LocalPolicyEngine(profile=policy_profile, network_profile=network_profile),
                tool_gateway,
                model_step=HarnessModelStep(
                    context_compiler=context_compiler,
                    available_tools=tool_gateway.model_tools,
                    conversation_compactor=context_compiler,
                ),
                synthesize_tool_results=True,
                parallel_safe_tools=tool_gateway.parallel_safe_tools,
                parallel_batch_limits=tool_gateway.parallel_batch_limits,
                max_parallel_tool_calls=3,
            ).run,
        )
    finally:
        tool_gateway.close()


class LocalToolGateway(ToolGatewayPort):
    def __init__(
        self,
        workspace_root: Path,
        *,
        model_gateway: ModelGatewayPort | None = None,
        research_child_limit: int = DEFAULT_RESEARCH_CHILD_LIMIT,
        tool_profile: ToolProfile = ToolProfile.GENERAL,
    ) -> None:
        if research_child_limit <= 0:
            raise ValueError("research_child_limit must be positive")
        if not isinstance(tool_profile, ToolProfile):
            raise ValueError("tool_profile is not supported")
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
        enabled_names = tool_names_for_profile(tool_profile)
        for tool in tools:
            if tool.contract.name in enabled_names:
                registry.register(tool.contract, tool.handle)
        self._subagents: LocalResearchSubagentCoordinator | None = None
        if model_gateway is not None and "agent.research" in enabled_names:
            self._subagents = LocalResearchSubagentCoordinator(
                LocalResearchSubagentRunner(model_gateway),
                max_children=research_child_limit,
                max_concurrency=research_child_limit,
            )
            research = ResearchSubagentTool(self._subagents, workspace_root)
            registry.register(research.contract, research.handle)
        self._model_tools = registry.model_tools()
        self._parallel_safe_tools = registry.parallel_safe_names()
        self._parallel_batch_limits = (
            {"agent.research": research_child_limit} if model_gateway is not None else {}
        )
        self._executor = ToolExecutor(registry)

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self._model_tools

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        return self._parallel_safe_tools

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return dict(self._parallel_batch_limits)

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

    def close(self) -> None:
        if self._subagents is not None:
            self._subagents.close()
