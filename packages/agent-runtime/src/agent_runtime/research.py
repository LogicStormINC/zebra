from __future__ import annotations

import json
from pathlib import Path
from threading import Event

from agent_context import LocalContextCompiler
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SubagentId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.subagents import (
    ResearchSource,
    ResearchSubagentResult,
    ResearchSubagentTask,
    SubagentStatus,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.subagents import SubagentPort
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_tools import (
    FileReadTool,
    GitStatusTool,
    ToolExecutor,
    ToolRegistry,
    WorkspaceSearchTool,
)
from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError, ToolRegistryError

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.subagents import (
    SubagentLimitError,
    cancelled_result,
)
from agent_runtime.workspace import LocalWorkspace

PROVENANCE = "local_read_only_research"


class LocalResearchSubagentRunner:
    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._model_gateway = model_gateway

    def __call__(
        self,
        subagent_id: SubagentId,
        task: ResearchSubagentTask,
        cancellation: Event,
    ) -> ResearchSubagentResult:
        if cancellation.is_set():
            return cancelled_result(subagent_id)
        tool_gateway = ReadOnlyToolGateway(task.workspace_root)
        compiler = LocalContextCompiler()
        result = HarnessLoop().run(
            HarnessTask(
                title="Read-only research",
                user_input=(
                    "Gather evidence for this objective using only the advertised read-only "
                    f"tools. Return a concise evidence-based summary. Objective: {task.objective}"
                ),
                max_attempts=1,
                max_model_calls=task.max_model_calls,
                max_tool_calls=task.max_tool_calls,
                workspace_root=task.workspace_root,
            ),
            SingleAttemptOrchestrator(
                self._model_gateway,
                LocalPolicyEngine(profile=PolicyProfile.READ_ONLY),
                tool_gateway,
                model_step=HarnessModelStep(
                    context_compiler=compiler,
                    available_tools=tool_gateway.model_tools,
                    conversation_compactor=compiler,
                ),
                synthesize_tool_results=True,
                parallel_safe_tools=tool_gateway.parallel_safe_tools,
                max_parallel_tool_calls=1,
            ).run,
        )
        sources = _research_sources(result.events)
        completed = result.run_result.final_outcome.value == "completed"
        status = SubagentStatus.COMPLETED if completed else SubagentStatus.FAILED
        summary = str(
            result.attempt_result.metadata.get(
                "assistant_message",
                result.attempt_result.summary,
            )
        ).strip()
        return ResearchSubagentResult(
            subagent_id=subagent_id,
            status=status,
            summary=summary or result.attempt_result.summary,
            sources=sources,
            confidence=1.0 if completed and sources else (0.5 if completed else 0.0),
            model_calls_used=result.run_result.model_calls_used,
            tool_calls_used=result.run_result.tool_calls_used,
            provenance=PROVENANCE,
        )


class ReadOnlyToolGateway(ToolGatewayPort):
    def __init__(self, workspace_root: Path) -> None:
        workspace = LocalWorkspace(workspace_root)
        workspace.ensure()
        registry = ToolRegistry()
        for tool in (
            FileReadTool(workspace),
            WorkspaceSearchTool(workspace),
            GitStatusTool(LocalRuntime(), workspace),
        ):
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
                metadata={"reason": "tool_validation_error", "detail": str(exc)},
            )


research_contract = ToolContract(
    name="agent.research",
    parallel_safe=True,
    required_arguments=("objective",),
    description="Delegate one bounded read-only workspace research task.",
    argument_properties={
        "objective": {
            "type": "string",
            "description": "Specific evidence-gathering objective for the child agent.",
        },
    },
)


class ResearchSubagentTool:
    def __init__(
        self,
        coordinator: SubagentPort,
        workspace_root: Path,
        *,
        max_model_calls: int = 3,
        max_tool_calls: int = 2,
        max_depth: int = 1,
    ) -> None:
        self._coordinator = coordinator
        self._workspace_root = workspace_root
        self._max_model_calls = max_model_calls
        self._max_tool_calls = max_tool_calls
        self._max_depth = max_depth

    @property
    def contract(self) -> ToolContract:
        return research_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        objective = tool_call.arguments["objective"]
        if not isinstance(objective, str) or not objective.strip():
            raise ToolArgumentError("agent.research requires a non-blank objective")
        task = ResearchSubagentTask(
            objective=objective.strip(),
            workspace_root=self._workspace_root,
            max_model_calls=self._max_model_calls,
            max_tool_calls=self._max_tool_calls,
            depth=1,
        )
        try:
            subagent_id = self._coordinator.spawn(task)
            result = self._coordinator.join(subagent_id)
        except SubagentLimitError as exc:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={"reason": "subagent_limit", "detail": str(exc)},
            )
        payload = {
            "subagent_id": str(result.subagent_id),
            "status": result.status.value,
            "summary": result.summary,
            "sources": [
                {"reference": source.reference, "kind": source.kind}
                for source in result.sources
            ],
            "confidence": result.confidence,
        }
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=(
                ToolCallStatus.EXECUTED
                if result.status is SubagentStatus.COMPLETED
                else ToolCallStatus.FAILED
            ),
            output=json.dumps(payload, separators=(",", ":"), sort_keys=True),
            metadata={
                "subagent_id": str(result.subagent_id),
                "subagent_status": result.status.value,
                "max_model_calls": self._max_model_calls,
                "max_tool_calls": self._max_tool_calls,
                "max_depth": self._max_depth,
                "model_calls_used": result.model_calls_used,
                "tool_calls_used": result.tool_calls_used,
                "source_count": len(result.sources),
                "confidence": result.confidence,
                "provenance": result.provenance,
            },
        )


def _research_sources(events: tuple[SessionEvent, ...]) -> tuple[ResearchSource, ...]:
    sources: list[ResearchSource] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
            continue
        tool_name = event.payload.get("tool_name")
        metadata = event.payload.get("metadata")
        if not isinstance(tool_name, str) or not isinstance(metadata, dict):
            continue
        key = "path" if tool_name in {"files.read", "files.search"} else "cwd"
        reference = metadata.get(key)
        if not isinstance(reference, str) or not reference.strip():
            continue
        identity = (reference.strip(), tool_name)
        if identity in seen:
            continue
        seen.add(identity)
        sources.append(ResearchSource(reference=identity[0], kind=identity[1]))
    return tuple(sources)
