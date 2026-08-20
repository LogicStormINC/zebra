from __future__ import annotations

import json
from pathlib import Path
from threading import Event

from agent_context import LocalContextCompiler
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SubagentId, TaskId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.subagents import (
    ResearchSource,
    ResearchSubagentResult,
    ResearchSubagentTask,
    SubagentStatus,
    research_evidence_gate,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.runtime import RuntimePort
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
    def __init__(
        self,
        model_gateway: ModelGatewayPort,
        *,
        runtime: RuntimePort | None = None,
    ) -> None:
        self._model_gateway = model_gateway
        # SUBAGENT-RUNTIME-01: children reuse the parent RuntimePort instead
        # of building their own LocalRuntime (P0.3).
        self._runtime = runtime

    def __call__(
        self,
        subagent_id: SubagentId,
        task: ResearchSubagentTask,
        cancellation: Event,
    ) -> ResearchSubagentResult:
        if cancellation.is_set():
            return cancelled_result(subagent_id)
        tool_gateway = ReadOnlyToolGateway(task.workspace_root, runtime=self._runtime)
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
        successful_tool_calls = sum(
            1
            for event in result.events
            if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
        )
        gate = research_evidence_gate(len(sources), successful_tool_calls)
        # SUBAGENT-EVIDENCE-GATE-01: zero-evidence research never completes.
        status = (
            SubagentStatus.COMPLETED
            if completed and gate.passed
            else SubagentStatus.FAILED
        )
        summary = str(
            result.attempt_result.metadata.get(
                "assistant_message",
                result.attempt_result.summary,
            )
        ).strip()
        return ResearchSubagentResult(
            subagent_id=subagent_id,
            status=status,
            summary=(
                summary or result.attempt_result.summary
                if status is SubagentStatus.COMPLETED
                else (
                    f"[gate:{gate.reason_code}] {summary or result.attempt_result.summary}"
                )
            ),
            sources=sources,
            confidence=1.0 if status is SubagentStatus.COMPLETED else 0.0,
            model_calls_used=result.run_result.model_calls_used,
            tool_calls_used=result.run_result.tool_calls_used,
            provenance=PROVENANCE,
        )


class ReadOnlyToolGateway(ToolGatewayPort):
    """SUBAGENT-TOOLSET-01: the researcher child toolset.

    Built through ChildToolsetFactoryPort semantics: read-only local tools
    plus an injected parent RuntimePort; no write surface, no agent.research.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        runtime: RuntimePort | None = None,
    ) -> None:
        workspace = LocalWorkspace(workspace_root)
        workspace.ensure()
        registry = ToolRegistry()
        for tool in (
            FileReadTool(workspace),
            WorkspaceSearchTool(workspace),
            GitStatusTool(runtime if runtime is not None else LocalRuntime(), workspace),
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
    required_arguments=("objective", "delegation_reason"),
    description=(
        "Delegate one bounded, independent, multi-step read-only research task when "
        "separate context is materially useful. Prefer direct answers and parent tools "
        "for simple work."
    ),
    argument_properties={
        "objective": {
            "type": "string",
            "description": "Specific evidence-gathering objective for the child agent.",
        },
        "delegation_reason": {
            "type": "string",
            "description": (
                "Concise reason this objective is better isolated than answered directly "
                "or completed with parent tools."
            ),
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
        wait_for_result: bool = True,
        delegation_store: object | None = None,
        parent_task_id: object | None = None,
        parent_binding_digest: str | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._workspace_root = workspace_root
        self._max_model_calls = max_model_calls
        self._max_tool_calls = max_tool_calls
        self._max_depth = max_depth
        self._wait_for_result = wait_for_result
        # Cloud durable mode: the store materializes the child as a real
        # PostgreSQL Task instead of a ThreadPool thread (plan 8.1/8.2).
        self._delegation_store = delegation_store
        self._parent_task_id = parent_task_id
        self._parent_binding_digest = parent_binding_digest

    def _delegate_durable(
        self, tool_call: ToolCall, objective: str, delegation_reason: str
    ) -> ToolResult:
        """Materialize a durable child Task via the PostgreSQL delegation store."""
        import json as _json

        from agent_core.application.session_bootstrap import (
            SessionBootstrapCommand as _SBC,
        )
        from agent_core.application.session_bootstrap import (
            SessionBootstrapService as _SBS,
        )
        from agent_core.application.workspace_projection import (
            rebuild_workspace as _rw,
        )
        from agent_core.domain.agent_capabilities import capability_set as _caps
        from agent_core.domain.subagent_delegation import (
            SubagentDelegationRequest as _SDR,
        )
        from agent_core.domain.subagents import SubagentRole as _Role
        from agent_core.ports.task_admission_transaction import (
            TaskAdmissionRequest as _TAR,
        )

        bootstrap = _SBS().build(
            _SBC(
                title=f"Research: {objective[:120]}",
                user_input=objective,
                workspace_root=Path(str(self._workspace_root)),
            )
        )
        child_admission = _TAR(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=_rw(list(bootstrap.events)),
        )
        # SessionId IS a UUID (NewType); use it directly, never invent one
        from uuid import UUID as _UUID

        parent_uuid = (
            self._parent_task_id
            if isinstance(self._parent_task_id, _UUID)
            else _UUID(str(self._parent_task_id))
            if self._parent_task_id
            else None
        )
        if parent_uuid is None:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output='{"reason": "durable_delegation_requires_parent_task_id"}',
                metadata={"reason": "durable_delegation_requires_parent_task_id"},
            )
        request = _SDR(
            parent_task_id=TaskId(parent_uuid),
            parent_attempt_number=1,
            parent_tool_call_id=str(tool_call.tool_call_id),
            delegation_index=0,
            role=_Role.RESEARCHER,
            objective=objective,
            requested_capabilities=frozenset(_caps(["evidence.read"])),
            child_definition_snapshot_digest="0" * 64,
            child_capability_profile_ref="profile/researcher@1",
            expected_parent_binding_digest=self._parent_binding_digest or "0" * 64,
        )
        from agent_storage.postgres.subagent_delegation import (
            PostgresSubagentDelegationStore,
        )

        assert isinstance(self._delegation_store, PostgresSubagentDelegationStore)
        receipt = self._delegation_store.delegate(request, child_admission)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=_json.dumps(
                {
                    "delegation_reason": delegation_reason.strip(),
                    "child_task_id": str(receipt.child_task_id),
                    "status": "materialized",
                    "resume": "durable_wakeup",
                    "replayed": receipt.status == "replayed",
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            metadata={
                "child_task_id": str(receipt.child_task_id),
                "subagent_status": "materialized",
                "durable_delegation": True,
                "delegation_reason": delegation_reason.strip(),
                "suspend_after_turn": True,
            },
        )

    @property
    def contract(self) -> ToolContract:
        return research_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        objective = tool_call.arguments["objective"]
        if not isinstance(objective, str) or not objective.strip():
            raise ToolArgumentError("agent.research requires a non-blank objective")
        delegation_reason = tool_call.arguments["delegation_reason"]
        if not isinstance(delegation_reason, str) or not delegation_reason.strip():
            raise ToolArgumentError(
                "agent.research requires a non-blank delegation_reason"
            )
        task = ResearchSubagentTask(
            objective=objective.strip(),
            workspace_root=self._workspace_root,
            max_model_calls=self._max_model_calls,
            max_tool_calls=self._max_tool_calls,
            depth=1,
        )
        try:
            if self._delegation_store is not None and not self._wait_for_result:
                return self._delegate_durable(tool_call, objective, delegation_reason)
            subagent_id = self._coordinator.spawn(task)
            if not self._wait_for_result:
                # SUBAGENT-CLOUD-CUTOVER-01: cloud parents never block on a
                # synchronous join; the durable wakeup resumes them when the
                # child settles (plan 8.2).
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    status=ToolCallStatus.EXECUTED,
                    output=json.dumps(
                        {
                            "delegation_reason": delegation_reason.strip(),
                            "subagent_id": str(subagent_id),
                            "status": "running",
                            "resume": "durable_wakeup",
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    metadata={
                        "subagent_id": str(subagent_id),
                        "subagent_status": "running",
                        "durable_delegation": True,
                        "delegation_reason": delegation_reason.strip(),
                    },
                )
            result = self._coordinator.join(subagent_id)
        except SubagentLimitError as exc:
            detail = str(exc)[:1000]
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output=json.dumps(
                    {"detail": detail, "reason": "subagent_limit", "status": "failed"},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                metadata={"reason": "subagent_limit", "detail": detail},
            )
        payload = {
            "delegation_reason": delegation_reason.strip(),
            "subagent_id": str(result.subagent_id),
            "status": result.status.value,
            "summary": result.summary,
            "sources": [
                {"reference": source.reference, "kind": source.kind}
                for source in result.sources
            ],
            "confidence": result.confidence,
            "usage": {
                "model_calls": result.model_calls_used,
                "tool_calls": result.tool_calls_used,
            },
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
                "delegation_reason": delegation_reason.strip(),
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
