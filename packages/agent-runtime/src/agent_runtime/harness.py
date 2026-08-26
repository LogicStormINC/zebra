from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.subagents import DelegationMode
from agent_core.domain.tool_profiles import ToolProfile, tool_names_for_profile
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.web import WebTarget, WebTargetError, parse_web_target
from agent_core.harness import HarnessLoop, HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness.models import HarnessLoopResult
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.context_compiler import ConfirmedMemoryInput
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_core.ports.session_history import SessionHistoryPort
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_security import DEFAULT_NETWORK_PROFILE, LocalPolicyEngine, NetworkProfile, PolicyProfile
from agent_tools import (
    AuthorizedMcpToolCatalog,
    ClarifyTool,
    CommandRunTool,
    FileReadTool,
    GitStatusTool,
    McpProxyToolGateway,
    McpToolDescribeTool,
    McpToolSearchTool,
    PatchApplyTool,
    PlanTool,
    SessionSearchTool,
    SkillsListTool,
    SkillsReadTool,
    TestsRunTool,
    ToolExecutor,
    ToolOutputProjector,
    ToolRegistry,
    WebFetchTool,
    WebGatewayTransport,
    WebSearchTool,
    WebSearchTransport,
    WorkspaceListTool,
    WorkspaceSearchTool,
)
from agent_tools.errors import ToolRegistryError
from agent_tools.skills_catalog import LocalSkillCatalog, ScopedSkillRoot, SkillEnablementState

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.mcp_protocol import McpAnyServerSpec
from agent_runtime.mcp_routing import build_mcp_transport
from agent_runtime.research import LocalResearchSubagentRunner, ResearchSubagentTool
from agent_runtime.subagents import LocalResearchSubagentCoordinator
from agent_runtime.tool_output_projection import build_output_projector
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_runtime.web_search import LocalWebSearchTransport
from agent_runtime.web_tools import register_native_web_tools
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
    web_search_endpoint: str | None = None,
    skill_roots: tuple[str | Path | ScopedSkillRoot, ...] = (),
    skills_state: SkillEnablementState | None = None,
    session_history: SessionHistoryPort | None = None,
    confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
    attachments: tuple[AttachmentContextInput, ...] = (),
    mcp_servers: Sequence[McpAnyServerSpec] = (),
    mcp_allowlist: Sequence[str] | None = None,
    trusted_local: bool = False,
    max_model_calls: int | None = None,
    max_tool_calls: int | None = None,
    web_pipeline_v2: bool = False,
    delegation_mode: DelegationMode = DelegationMode.AUTO,
) -> HarnessLoopResult:
    tool_gateway = LocalToolGateway(
        workspace_root,
        model_gateway=model_gateway,
        tool_profile=tool_profile,
        web_search_endpoint=web_search_endpoint,
        skill_roots=skill_roots,
        skills_state=skills_state,
        session_history=session_history,
        mcp_servers=mcp_servers,
        mcp_allowlist=mcp_allowlist,
        trusted_local=trusted_local,
        web_pipeline_v2=web_pipeline_v2,
        delegation_mode=delegation_mode,
    )
    resolved_mcp_allowlist = (
        tuple(tool.name for tool in tool_gateway.effective_mcp_tools)
        if mcp_allowlist is None
        else tuple(mcp_allowlist)
    )
    context_compiler = LocalContextCompiler()
    try:
        return HarnessLoop().run(
            HarnessTask(
                title=title,
                user_input=prompt,
                max_attempts=1,
                max_model_calls=max_model_calls,
                max_tool_calls=max_tool_calls,
                workspace_root=workspace_root,
                policy_profile=policy_profile.value,
                tool_profile=tool_profile,
                network_profile=network_profile.name.value,
                network_allowlist=network_profile.domain_allowlist,
                mcp_allowlist=resolved_mcp_allowlist,
                skill_components=tool_gateway.effective_skill_components,
                confirmed_memories=confirmed_memories,
                attachments=attachments,
            ),
            SingleAttemptOrchestrator(
                model_gateway,
                LocalPolicyEngine(
                    profile=policy_profile,
                    network_profile=network_profile,
                    web_search_endpoint=web_search_endpoint,
                    trusted_local=trusted_local,
                    web_pipeline_v2=web_pipeline_v2,
                ),
                tool_gateway,
                model_step=HarnessModelStep(
                    context_compiler=context_compiler,
                    available_tools=tool_gateway.model_tools,
                    conversation_compactor=context_compiler,
                    delegation_mode=delegation_mode.value,
                ),
                synthesize_tool_results=True,
                parallel_safe_tools=tool_gateway.parallel_safe_tools,
                parallel_batch_limits=tool_gateway.parallel_batch_limits,
                max_parallel_tool_calls=3,
                tool_call_resolver=tool_gateway.resolve_model_tool_calls,
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
        delegation_mode: DelegationMode = DelegationMode.AUTO,
        durable_delegation: bool = False,
        delegation_store: object | None = None,
        parent_task_id: object | None = None,
        parent_binding_digest: str | None = None,
        parent_binding: object | None = None,
        parent_context: ContextMaterialization | None = None,
        tool_profile: ToolProfile = ToolProfile.GENERAL,
        web_gateway_transport: WebGatewayTransport | None = None,
        web_search_endpoint: str | None = None,
        web_search_transport: WebSearchTransport | None = None,
        skill_roots: tuple[str | Path | ScopedSkillRoot, ...] = (),
        skills_state: SkillEnablementState | None = None,
        session_history: SessionHistoryPort | None = None,
        current_session_id: str | None = None,
        mcp_servers: Sequence[McpAnyServerSpec] = (),
        mcp_allowlist: Sequence[str] | None = None,
        runtime: RuntimePort | None = None,
        runtime_handle: RuntimeHandle | None = None,
        artifact_payload_store: ArtifactPayloadStorePort | None = None,
        output_projector: ToolOutputProjector | None = None,
        trusted_local: bool = False,
        web_pipeline_v2: bool = False,
    ) -> None:
        if research_child_limit <= 0:
            raise ValueError("research_child_limit must be positive")
        if not isinstance(tool_profile, ToolProfile):
            raise ValueError("tool_profile is not supported")
        if mcp_allowlist and not mcp_servers:
            raise ValueError(
                f"selected MCP tools are unavailable: {', '.join(sorted(mcp_allowlist))}"
            )
        self._workspace = LocalWorkspace(workspace_root)
        self._workspace.ensure()
        self._runtime = runtime or LocalRuntime()
        self._runtime_handle = runtime_handle
        if artifact_payload_store is not None and output_projector is not None:
            raise ValueError("configure one Tool output persistence strategy")
        output_projector = output_projector or build_output_projector(
            artifact_payload_store, current_session_id=current_session_id
        )
        self._output_projector = output_projector
        registry = ToolRegistry()
        tools = (
            ClarifyTool(),
            PlanTool(),
            WorkspaceListTool(
                self._workspace,
                max_output_bytes=None if output_projector is not None else 32_768,
            ),
            FileReadTool(
                self._workspace,
                max_bytes=None if output_projector is not None else 16_384,
            ),
            WorkspaceSearchTool(
                self._workspace,
                max_output_bytes=None if output_projector is not None else 32_768,
            ),
            GitStatusTool(self._runtime, self._workspace),
            PatchApplyTool(self._runtime, self._workspace),
            TestsRunTool(
                self._runtime,
                self._workspace,
                DEFAULT_TEST_PRESETS,
            ),
            CommandRunTool(self._runtime, self._workspace),
        )
        enabled_names = tool_names_for_profile(tool_profile)
        for tool in tools:
            if tool.contract.name in enabled_names:
                registry.register(tool.contract, tool.handle)
        self._register_web_tools(
            registry,
            enabled_names=enabled_names,
            workspace_root=workspace_root,
            web_gateway_transport=web_gateway_transport,
            web_search_endpoint=web_search_endpoint,
            web_search_transport=web_search_transport,
            trusted_local=trusted_local,
            output_projector=output_projector,
            web_pipeline_v2=web_pipeline_v2,
        )
        self._skill_component_names: tuple[str, ...] = ()
        if skill_roots:
            catalog = LocalSkillCatalog(skill_roots, skills_state=skills_state)
            self._skill_component_names = tuple(
                metadata.name for metadata in catalog.list()[0]
            )
            for skill_tool in (SkillsListTool(catalog), SkillsReadTool(catalog)):
                if skill_tool.contract.name in enabled_names:
                    registry.register(skill_tool.contract, skill_tool.handle)
        if session_history is not None and "sessions.search" in enabled_names:
            history_tool = SessionSearchTool(session_history, current_session_id)
            registry.register(history_tool.contract, history_tool.handle)
        mcp_transport = build_mcp_transport(
            mcp_servers,
            mcp_allowlist,
            max_output_bytes=None if output_projector is not None else 32_768,
        )
        self._mcp_catalog = AuthorizedMcpToolCatalog(
            mcp_transport.model_tools if mcp_transport is not None else ()
        )
        if self._mcp_catalog.activated:
            for catalog_tool in (
                McpToolSearchTool(self._mcp_catalog),
                McpToolDescribeTool(self._mcp_catalog),
            ):
                registry.register(catalog_tool.contract, catalog_tool.handle)
        self._subagents: LocalResearchSubagentCoordinator | None = None
        self._delegation_mode = delegation_mode
        if (
            model_gateway is not None
            and "agent.research" in enabled_names
            and delegation_mode is not DelegationMode.DISABLED
        ):
            self._subagents = LocalResearchSubagentCoordinator(
                LocalResearchSubagentRunner(model_gateway, runtime=runtime),
                max_children=research_child_limit,
                max_concurrency=research_child_limit,
            )
            research = ResearchSubagentTool(
                self._subagents,
                workspace_root,
                wait_for_result=not durable_delegation,
                delegation_store=delegation_store,
                parent_task_id=parent_task_id,
                parent_binding=parent_binding,
                parent_context=parent_context,
            )
            registry.register(research.contract, research.handle)
        self._model_tools = registry.model_tools() + self._mcp_catalog.model_tools
        self._parallel_safe_tools = registry.parallel_safe_names()
        self._parallel_batch_limits = (
            {"agent.research": research_child_limit} if model_gateway is not None else {}
        )
        self._executor = ToolExecutor(
            registry,
            mcp_proxy_gateway=(
                McpProxyToolGateway(mcp_transport) if mcp_transport is not None else None
            ),
        )

    def _register_web_tools(
        self,
        registry: ToolRegistry,
        *,
        enabled_names: frozenset[str],
        workspace_root: Path,
        web_gateway_transport: WebGatewayTransport | None,
        web_search_endpoint: str | None,
        web_search_transport: WebSearchTransport | None,
        trusted_local: bool,
        output_projector: ToolOutputProjector | None,
        web_pipeline_v2: bool,
    ) -> None:
        search_endpoint = _optional_web_search_endpoint(
            web_search_endpoint,
            web_pipeline_v2=web_pipeline_v2,
        )
        if web_pipeline_v2:
            if web_gateway_transport is not None or web_search_transport is not None:
                raise ValueError(
                    "legacy web transports are not supported when web_pipeline_v2 is enabled"
                )
            # Native v2 path (opt-in via ZEBRA_WEB_PIPELINE_V2). See web_tools.py.
            register_native_web_tools(
                registry,
                enabled_names=enabled_names,
                workspace_root=workspace_root,
                search_endpoint=search_endpoint,
                trusted_local=trusted_local,
            )
            return
        # Legacy v1 path (default). Preserves durable network-authority behavior
        # guarded by tests/worker/test_approved_continuation.py — do not flip the
        # default until v2 replicates that authority (see WEB-PIPE §14.2).
        fetch_transport = web_gateway_transport or LocalWebGatewayTransport(
            use_system_proxy=trusted_local
        )
        legacy_fetch = WebFetchTool(
            fetch_transport,
            max_output_bytes=262_144 if output_projector is not None else 65_536,
        )
        if "web.fetch" in enabled_names:
            registry.register(legacy_fetch.contract, legacy_fetch.handle)
        if search_endpoint is not None and "web.search" in enabled_names:
            legacy_search = WebSearchTool(
                endpoint=search_endpoint,
                transport=web_search_transport
                or LocalWebSearchTransport(use_system_proxy=trusted_local),
            )
            registry.register(legacy_search.contract, legacy_search.handle)

    @property
    def delegation_mode(self) -> DelegationMode:
        return self._delegation_mode

    @property
    def delegation_attempted(self) -> bool:
        return self._subagents is not None and self._subagents.delegation_attempted

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self._model_tools

    @property
    def effective_mcp_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self._mcp_catalog.definitions

    @property
    def effective_skill_components(self) -> tuple[str, ...]:
        return self._skill_component_names

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        return self._parallel_safe_tools

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return dict(self._parallel_batch_limits)

    def execute(self, tool_call: ToolCall) -> ToolResult:
        try:
            result = self._executor.execute(tool_call)
            return self._project_tool_output(tool_call, result)
        except ToolRegistryError as exc:
            detail = str(exc)[:1000]
            failed = ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output=json.dumps(
                    {
                        "detail": detail,
                        "reason": "tool_validation_error",
                        "status": "failed",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                metadata={
                    "reason": "tool_validation_error",
                    "detail": detail,
                },
            )
            return self._project_tool_output(tool_call, failed)

    def _project_tool_output(self, tool_call: ToolCall, result: ToolResult) -> ToolResult:
        if self._output_projector is None:
            return result
        existing_uri = result.metadata.get("artifact_uri")
        if isinstance(existing_uri, str) and existing_uri.strip():
            return result
        stderr = result.metadata.get("stderr")
        if tool_call.name in {"command.run", "tests.run"} and isinstance(stderr, str):
            projected = self._output_projector.project(
                stdout=result.output,
                stderr=stderr,
                artifact_name=f"{tool_call.name.replace('.', '-')}.txt",
                provenance={
                    "tool_name": tool_call.name,
                    "tool_call_id": str(tool_call.tool_call_id),
                },
            )
            metadata = {**result.metadata, "stderr": "", **projected.metadata}
        else:
            projected = self._output_projector.project_text(
                result.output,
                artifact_name=f"{tool_call.name.replace('.', '-')}.txt",
                provenance={
                    "tool_name": tool_call.name,
                    "tool_call_id": str(tool_call.tool_call_id),
                },
            )
            metadata = {**result.metadata, **projected.metadata}
        return ToolResult(
            tool_call_id=result.tool_call_id,
            status=result.status,
            output=projected.model_output,
            metadata=metadata,
        )

    def resolve_model_tool_calls(
        self,
        tool_calls: tuple[ToolCall, ...],
    ) -> tuple[ToolCall, ...]:
        return tuple(self._mcp_catalog.resolve(tool_call) for tool_call in tool_calls)

    def close(self) -> None:
        try:
            if self._subagents is not None:
                self._subagents.close()
        finally:
            if self._runtime_handle is not None:
                self._runtime.destroy(self._runtime_handle)
                self._runtime_handle = None

def _optional_web_search_endpoint(
    value: str | None,
    *,
    web_pipeline_v2: bool = False,
) -> WebTarget | None:
    if value is None:
        return None
    try:
        return parse_web_target(value)
    except WebTargetError as exc:
        if web_pipeline_v2:
            raise ValueError(
                f"web_search_endpoint is not a valid web target for web_pipeline_v2: {exc}"
            ) from exc
        return None
