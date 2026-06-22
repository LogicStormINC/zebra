from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness.models import HarnessLoopResult
from agent_core.harness.projection import HarnessTraceProjector
from agent_integrations import build_model_gateway
from agent_runtime import LocalRuntime, LocalWorkspace
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
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
from zebra_agent_config import ZebraAgentSettings

DEFAULT_TEST_PRESETS = {
    "pytest": ("uv", "run", "pytest"),
    "check": ("make", "check"),
    "test": ("make", "test"),
}


@dataclass(frozen=True)
class DurableRunResult:
    harness_result: HarnessLoopResult
    workspace_root: Path
    policy_profile: str


def execute_durable_run(
    *,
    prompt: str,
    title: str,
    workspace_root: Path,
    database_path: Path,
    settings: ZebraAgentSettings,
    policy_profile: PolicyProfile = PolicyProfile.WORKSPACE_WRITE,
) -> DurableRunResult:
    result = HarnessLoop().run(
        HarnessTask(
            title=title,
            user_input=prompt,
            max_attempts=1,
            max_model_calls=1,
            max_tool_calls=1,
            workspace_root=workspace_root,
        ),
        SingleAttemptOrchestrator(
            build_model_gateway(settings),
            LocalPolicyEngine(profile=policy_profile),
            _LocalToolGateway(workspace_root),
        ).run,
    )
    event_store = SQLiteEventStore(database_path)
    for event in result.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(result.session)
    return DurableRunResult(
        harness_result=result,
        workspace_root=workspace_root,
        policy_profile=policy_profile.value,
    )


def serialize_run_execution(result: DurableRunResult) -> dict[str, object]:
    harness_result = result.harness_result
    trace = HarnessTraceProjector().project(harness_result)
    return {
        "executed": True,
        "status": harness_result.session.status.value,
        "attempts_used": harness_result.run_result.attempts_used,
        "stop_reason": harness_result.run_result.stop_reason.value,
        "assistant_message": harness_result.attempt_result.metadata.get("assistant_message"),
        "policy_profile": result.policy_profile,
        "workspace_root": str(result.workspace_root),
        "trace": [
            {
                "attempt_number": attempt.attempt_number,
                "assistant_message": attempt.assistant_message,
                "tools": [
                    {
                        "tool_name": tool.tool_name,
                        "status": tool.status,
                        "arguments": tool.arguments,
                        "output": tool.output,
                        "metadata": tool.metadata,
                        "policy_decision": tool.policy_decision,
                    }
                    for tool in attempt.tools
                ],
            }
            for attempt in trace.attempts
        ],
    }


class _LocalToolGateway:
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
