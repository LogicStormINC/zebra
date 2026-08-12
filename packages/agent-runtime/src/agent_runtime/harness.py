from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_context import LocalContextCompiler
from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.model_media import ModelInputModality, ModelMediaInput
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.skills import SkillComponentIdentity
from agent_core.domain.tool_profiles import ToolProfile, tool_names_for_profile
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.web import WebTarget, WebTargetError, parse_web_target
from agent_core.harness import HarnessLoop, HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness.model_capabilities import declared_model_capabilities
from agent_core.harness.models import HarnessLoopResult
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.context_compiler import ConfirmedMemoryInput
from agent_core.ports.model_gateway import (
    ModelGatewayPort,
    ModelMediaCapabilityPort,
    ModelMediaResolverBinderPort,
    ModelMediaResolverPort,
)
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_core.ports.session_history import SessionHistoryPort
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_security import (
    DEFAULT_NETWORK_PROFILE,
    LocalPolicyEngine,
    NetworkProfile,
    NetworkProfileName,
    PolicyProfile,
)
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
    resolve_agent_definition_context,
)
from agent_tools.contracts import READ_ONLY_EFFECT_TAG
from agent_tools.errors import ToolRegistryError
from agent_tools.skills_catalog import LocalSkillCatalog, ScopedSkillRoot, SkillEnablementState

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.artifact_output_contract import (
    ArtifactOutputContractEmitTool,
)
from agent_runtime.finos_journal_provider import (
    TRUSTED_TYPED_EVIDENCE_TAG_PREFIX,
    FinosJournalProvider,
    trusted_typed_evidence_result,
)
from agent_runtime.mcp_protocol import McpAnyServerSpec
from agent_runtime.mcp_routing import build_mcp_transport
from agent_runtime.research import LocalResearchSubagentRunner, ResearchSubagentTool
from agent_runtime.subagents import LocalResearchSubagentCoordinator
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


def bind_native_media_inputs(
    model_gateway: ModelGatewayPort,
    media_inputs: tuple[ModelMediaInput, ...],
    media_resolver: ModelMediaResolverPort,
) -> tuple[ModelMediaInput, ...]:
    """Bind task-scoped media only when the selected gateway advertises it."""
    if not media_inputs:
        return ()
    if not isinstance(model_gateway, ModelMediaCapabilityPort):
        return ()
    if ModelInputModality.IMAGE not in model_gateway.media_capabilities.input_modalities:
        return ()
    if not isinstance(model_gateway, ModelMediaResolverBinderPort):
        raise ValueError("native media gateway cannot bind its task resolver")
    model_gateway.bind_media_resolver(media_resolver)
    return media_inputs


def run_local_harness(
    *,
    prompt: str,
    public_content: str | None = None,
    title: str,
    workspace_root: Path,
    model_gateway: ModelGatewayPort,
    policy_profile: PolicyProfile = PolicyProfile.WORKSPACE_WRITE,
    tool_profile: ToolProfile = ToolProfile.GENERAL,
    network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE,
    web_search_endpoint: str | None = None,
    skill_roots: tuple[str | Path | ScopedSkillRoot, ...] = (),
    skills_state: SkillEnablementState | None = None,
    granted_skill_component_identities: tuple[SkillComponentIdentity, ...] | None = None,
    session_history: SessionHistoryPort | None = None,
    confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
    attachments: tuple[AttachmentContextInput, ...] = (),
    media_inputs: tuple[ModelMediaInput, ...] = (),
    mcp_servers: Sequence[McpAnyServerSpec] = (),
    mcp_allowlist: Sequence[str] | None = None,
    preapproved_readonly_tools: Sequence[str] = (),
    disabled_mcp_tools: Sequence[str] = (),
    agent_definition: AgentDefinition | None = None,
    model_id: str | None = None,
    trusted_local: bool = False,
    max_model_calls: int | None = None,
    max_tool_calls: int | None = None,
    plan_required: bool = False,
    web_pipeline_v2: bool = False,
    session_id: SessionId | None = None,
    initial_user_event_id: EventId | None = None,
) -> HarnessLoopResult:
    tool_gateway = LocalToolGateway(
        workspace_root,
        model_gateway=model_gateway,
        tool_profile=tool_profile,
        network_profile=network_profile,
        policy_profile=policy_profile,
        web_search_endpoint=web_search_endpoint,
        skill_roots=skill_roots,
        skills_state=skills_state,
        granted_skill_component_identities=granted_skill_component_identities,
        session_history=session_history,
        mcp_servers=mcp_servers,
        mcp_allowlist=mcp_allowlist,
        disabled_mcp_tools=disabled_mcp_tools,
        trusted_local=trusted_local,
        web_pipeline_v2=web_pipeline_v2,
    )
    effective_mcp_allowlist = tuple(
        tool.name for tool in tool_gateway.effective_mcp_tools
    )
    effective_preapproved_readonly_tools = tuple(
        tool_name
        for tool_name in preapproved_readonly_tools
        if tool_name in effective_mcp_allowlist
    )
    agent_context = resolve_agent_definition_context(agent_definition, skill_roots, skills_state)
    context_compiler = LocalContextCompiler()
    try:
        return HarnessLoop().run(
            HarnessTask(
                title=title,
                user_input=prompt,
                public_content=public_content,
                max_attempts=1,
                max_model_calls=max_model_calls,
                max_tool_calls=max_tool_calls,
                plan_required=plan_required,
                workspace_root=workspace_root,
                policy_profile=policy_profile.value,
                tool_profile=tool_profile,
                network_profile=network_profile.name.value,
                network_allowlist=network_profile.domain_allowlist,
                mcp_allowlist=effective_mcp_allowlist,
                preapproved_readonly_tools=effective_preapproved_readonly_tools,
                skill_components=tool_gateway.effective_skill_components,
                skill_component_identities=tool_gateway.effective_skill_component_identities,
                agent_definition=agent_definition,
                trusted_evidence_tools=tool_gateway.trusted_evidence_tools,
                model_id=model_id,
                agent_context=agent_context,
                model_capabilities=declared_model_capabilities(
                    model_gateway, bool(tool_gateway.model_tools)
                ),
                confirmed_memories=confirmed_memories,
                attachments=attachments,
                media_inputs=media_inputs,
            ),
            SingleAttemptOrchestrator(
                model_gateway,
                LocalPolicyEngine(
                    profile=policy_profile,
                    network_profile=network_profile,
                    web_search_endpoint=web_search_endpoint,
                    mcp_allowlist=effective_mcp_allowlist,
                    preapproved_readonly_tools=effective_preapproved_readonly_tools,
                    trusted_local=trusted_local,
                    web_pipeline_v2=web_pipeline_v2,
                ),
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
                tool_call_resolver=tool_gateway.resolve_model_tool_calls,
                validator_tool_names=tool_gateway.validator_tools,
            ).run,
            session_id=session_id,
            initial_user_event_id=initial_user_event_id,
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
        network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE,
        policy_profile: PolicyProfile = PolicyProfile.READ_ONLY,
        web_gateway_transport: WebGatewayTransport | None = None,
        web_search_endpoint: str | None = None,
        web_search_transport: WebSearchTransport | None = None,
        skill_roots: tuple[str | Path | ScopedSkillRoot, ...] = (),
        skills_state: SkillEnablementState | None = None,
        granted_skill_component_identities: tuple[SkillComponentIdentity, ...] | None = None,
        session_history: SessionHistoryPort | None = None,
        current_session_id: str | None = None,
        mcp_servers: Sequence[McpAnyServerSpec] = (),
        mcp_allowlist: Sequence[str] | None = None,
        disabled_mcp_tools: Sequence[str] = (),
        runtime: RuntimePort | None = None,
        runtime_handle: RuntimeHandle | None = None,
        artifact_payload_store: ArtifactPayloadStorePort | None = None,
        finos_journal_provider: FinosJournalProvider | None = None,
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
        self._disabled_mcp_tools = frozenset(name.strip() for name in disabled_mcp_tools)
        if any(not name for name in self._disabled_mcp_tools):
            raise ValueError("disabled MCP tool names must not be blank")
        self._network_profile = network_profile
        self._policy_profile = policy_profile
        self._workspace = LocalWorkspace(workspace_root)
        self._workspace.ensure()
        self._runtime = runtime or LocalRuntime()
        self._runtime_handle = runtime_handle
        output_projector = _output_projector(
            artifact_payload_store,
            current_session_id=current_session_id,
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
        if tool_profile is ToolProfile.GENERAL and policy_profile is PolicyProfile.READ_ONLY:
            enabled_names -= {"command.run", "patch.apply"}
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
        if finos_journal_provider is not None:
            finos_journal_provider.register(
                registry,
                allow_journal_save=(
                    self._policy_profile is not PolicyProfile.READ_ONLY
                ),
            )
        output_contract_tool = ArtifactOutputContractEmitTool()
        registry.register(
            output_contract_tool.contract,
            output_contract_tool.handle,
            tags=("artifact_metadata",),
        )
        self._skill_component_names: tuple[str, ...] = ()
        self._skill_component_identities: tuple[SkillComponentIdentity, ...] = ()
        if granted_skill_component_identities and not skill_roots:
            raise ValueError("granted skill component identities require configured skill roots")
        if skill_roots:
            catalog = LocalSkillCatalog(
                skill_roots,
                skills_state=skills_state,
                granted_component_identities=granted_skill_component_identities,
            )
            skill_metadata = catalog.list()[0]
            self._skill_component_names = tuple(metadata.name for metadata in skill_metadata)
            self._skill_component_identities = tuple(
                metadata.component_identity() for metadata in skill_metadata
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
            tuple(
                tool
                for tool in (mcp_transport.model_tools if mcp_transport is not None else ())
                if tool.name not in self._disabled_mcp_tools
            )
        )
        if self._mcp_catalog.activated:
            for catalog_tool in (
                McpToolSearchTool(self._mcp_catalog),
                McpToolDescribeTool(self._mcp_catalog),
            ):
                registry.register(catalog_tool.contract, catalog_tool.handle)
        self._subagents: LocalResearchSubagentCoordinator | None = None
        if model_gateway is not None and "agent.research" in enabled_names:
            self._subagents = LocalResearchSubagentCoordinator(
                LocalResearchSubagentRunner(model_gateway),
                max_children=research_child_limit,
                max_concurrency=research_child_limit,
            )
            research = ResearchSubagentTool(self._subagents, workspace_root)
            registry.register(research.contract, research.handle)
        self._validator_tools = registry.names_with_tag("validator")
        self._read_only_tools = registry.names_with_tag(READ_ONLY_EFFECT_TAG)
        self._trusted_typed_evidence = {
            name: tuple(
                dict.fromkeys(
                    tag.removeprefix(TRUSTED_TYPED_EVIDENCE_TAG_PREFIX)
                    for tag in registry.get(name).tags
                    if tag.startswith(TRUSTED_TYPED_EVIDENCE_TAG_PREFIX)
                    and tag.removeprefix(TRUSTED_TYPED_EVIDENCE_TAG_PREFIX)
                )
            )
            for name in registry.names()
        }
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
            # Tool visibility must match network authority: under
            # mcp-proxy-only (or any profile without direct web egress) a
            # web.fetch call is always DENY with no recovery, so exposing the
            # tool only invites a guaranteed session failure. Only profiles
            # that can actually allow direct fetch see the tool.
            # Tool visibility must match network authority: profiles without
            # direct web egress (mcp-proxy-only, git-proxy-only, setup-only)
            # always DENY web.fetch with no recovery, so exposing the tool
            # only invites a guaranteed session failure. Only profiles that
            # can actually allow fetch (full-trusted-local,
            # domain-allowlist) plus the legacy NONE durable-authority path
            # see the tool.
            if self._network_profile.name in {
                NetworkProfileName.NONE,
                NetworkProfileName.DOMAIN_ALLOWLIST,
                NetworkProfileName.FULL_TRUSTED_LOCAL,
            }:
                registry.register(legacy_fetch.contract, legacy_fetch.handle)
        if search_endpoint is not None and "web.search" in enabled_names:
            legacy_search = WebSearchTool(
                endpoint=search_endpoint,
                transport=web_search_transport
                or LocalWebSearchTransport(use_system_proxy=trusted_local),
            )
            registry.register(legacy_search.contract, legacy_search.handle)

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
    def effective_skill_component_identities(self) -> tuple[SkillComponentIdentity, ...]:
        return self._skill_component_identities

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        return self._parallel_safe_tools

    @property
    def validator_tools(self) -> frozenset[str]:
        return self._validator_tools

    @property
    def read_only_tools(self) -> frozenset[str]:
        return self._read_only_tools

    @property
    def trusted_evidence_tools(self) -> dict[str, tuple[str, ...]]:
        advertised = {tool.name for tool in self._model_tools}
        return {
            name: labels
            for name, labels in self._trusted_typed_evidence.items()
            if labels and name in advertised
        }

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return dict(self._parallel_batch_limits)

    def execute(self, tool_call: ToolCall) -> ToolResult:
        if tool_call.name in self._disabled_mcp_tools:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output="",
                metadata={"reason": "mcp_tool_unavailable"},
            )
        try:
            result = self._executor.execute(tool_call)
            return trusted_typed_evidence_result(
                self._project_tool_output(tool_call, result),
                trusted_evidence=self._trusted_typed_evidence.get(tool_call.name, ()),
            )
        except ToolRegistryError as exc:
            detail = str(exc)[:1000]
            return ToolResult(
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

    def _project_tool_output(self, tool_call: ToolCall, result: ToolResult) -> ToolResult:
        if self._output_projector is None:
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
        resolved = tuple(self._mcp_catalog.resolve(tool_call) for tool_call in tool_calls)
        if any(tool_call.name in self._disabled_mcp_tools for tool_call in resolved):
            raise ValueError("MCP tool is unavailable for this task")
        return resolved

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


def _output_projector(
    store: ArtifactPayloadStorePort | None,
    *,
    current_session_id: str | None,
) -> ToolOutputProjector | None:
    if store is None:
        return None
    if current_session_id is None:
        raise ValueError("artifact output projection requires current_session_id")
    try:
        session_id = SessionId(UUID(current_session_id))
    except ValueError as exc:
        raise ValueError("current_session_id must be a UUID") from exc

    def persist(content: str, file_name: str) -> str:
        stored = store.store_payload(
            ArtifactPayloadWrite(
                session_id=session_id,
                kind="tool_output",
                mime_type="text/plain",
                payload=content.encode("utf-8"),
                file_name=file_name,
                created_at=datetime.now(UTC),
            )
        )
        return stored.uri

    return ToolOutputProjector(persist)
