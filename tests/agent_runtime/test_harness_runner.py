import sys
from datetime import UTC, datetime

import pytest
from agent_context import TOMBSTONE_MARKER
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.memories import MemoryType
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.session_history import (
    SessionHistoryMode,
    SessionHistoryRequest,
    SessionHistoryResult,
    SessionHistorySummary,
)
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports.context_compiler import ConfirmedMemoryInput
from agent_runtime import LocalToolGateway, run_local_harness
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_runtime.web_search import LocalWebSearchTransport
from agent_security import LocalPolicyEngine, PolicyProfile, parse_network_profile
from agent_storage import SQLiteArtifactPayloadStore
from zebra_agent_config import McpServerSettings


class EmptyHistory:
    def query(self, request: SessionHistoryRequest) -> SessionHistoryResult:
        return SessionHistoryResult(mode=request.mode)


class ProofHistory:
    def query(self, request: SessionHistoryRequest) -> SessionHistoryResult:
        assert request.mode is SessionHistoryMode.SEARCH
        assert request.query == "continuity proof"
        return SessionHistoryResult(
            mode=request.mode,
            sessions=(
                SessionHistorySummary(
                    session_id="7d5fae1f-b466-4334-b969-1eafcb118202",
                    title="Prior task",
                    status="completed",
                    created_at=_created_at(),
                    updated_at=_created_at(),
                    snippet="HISTORY-RECALL-PROOF",
                    match_count=1,
                ),
            ),
            scanned_sessions=1,
            scanned_messages=2,
        )


def test_run_local_harness_completes_without_tool_calls(tmp_path) -> None:
    result = run_local_harness(
        prompt="Summarize the repository.",
        title="Runtime harness test",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Repository summary.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        ),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Repository summary."


def test_run_local_harness_executes_builtin_file_read(tmp_path) -> None:
    (tmp_path / "README.md").write_text("runtime readme\n", encoding="utf-8")
    result = run_local_harness(
        prompt="Read the repository README.",
        title="Runtime harness tool test",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Inspecting README.",
                            created_at=_created_at(),
                        ),
                        tool_calls=(
                            ToolCall(
                                tool_call_id=new_tool_call_id(),
                                name="files.read",
                                arguments={"path": "README.md"},
                                created_at=_created_at(),
                            ),
                        ),
                    )
                ),
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="The README contains: runtime readme",
                            created_at=_created_at(),
                        )
                    )
                ),
            ),
        ),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["tool_name"] == "files.read"
    assert result.attempt_result.metadata["tool_output"] == "runtime readme\n"
    assert result.attempt_result.metadata["assistant_message"] == (
        "The README contains: runtime readme"
    )
    assert result.run_result.model_calls_used == 2


def test_run_local_harness_has_no_implicit_tool_budget(tmp_path) -> None:
    paths = tuple(f"proof-{index}.txt" for index in range(4))
    for path in paths:
        (tmp_path / path).write_text(path, encoding="utf-8")
    responses = [
        ScriptedModelResponse(
            completion=_completion(
                f"Reading {path}.",
                ToolCall(
                    tool_call_id=new_tool_call_id(),
                    name="files.read",
                    arguments={"path": path},
                    created_at=_created_at(),
                ),
            )
        )
        for path in paths
    ]
    responses.extend(
        (
            ScriptedModelResponse(completion=_completion("All four files read.")),
            ScriptedModelResponse(
                completion=_completion("Recovered final from all four proof files.")
            ),
        )
    )

    gateway = ScriptedModelGateway(responses=tuple(responses))
    result = run_local_harness(
        prompt="Read every proof file.",
        title="Unlimited local harness budget",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == (
        "Recovered final from all four proof files."
    )
    assert result.run_result.model_calls_used == 6
    assert result.run_result.tool_calls_used == 4
    assert result.run_result.max_model_calls is None
    assert result.run_result.max_tool_calls is None
    assert len(gateway.tool_requests) == 6
    assert all(gateway.tool_requests[:5])
    assert gateway.tool_requests[-1] == ()
    assert TOMBSTONE_MARKER not in "\n".join(
        message.content for message in gateway.requests[-1]
    )
    assert all(
        any(
            message.role is MessageRole.TOOL and message.content == path
            for message in gateway.requests[-1]
        )
        for path in paths
    )


def test_run_local_harness_searches_then_reads_workspace_evidence(tmp_path) -> None:
    (tmp_path / "proof.txt").write_text("SEARCH-THEN-READ\n", encoding="utf-8")
    search_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.search",
        arguments={"query": "SEARCH-THEN-READ"},
        created_at=_created_at(),
    )
    read_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "proof.txt"},
        created_at=_created_at(),
    )
    result = run_local_harness(
        prompt="Find and read the proof.",
        title="Runtime search and read test",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=tuple(
                ScriptedModelResponse(completion=completion)
                for completion in (
                    _completion("Searching.", search_call),
                    _completion("Reading.", read_call),
                    _completion("Found SEARCH-THEN-READ."),
                )
            )
        ),
    )

    executed = [
        event.payload["tool_name"]
        for event in result.events
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
    ]
    assert executed == ["files.search", "files.read"]
    assert result.attempt_result.metadata["assistant_message"] == "Found SEARCH-THEN-READ."


def test_run_local_harness_lists_then_reads_workspace_evidence(tmp_path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "brief.txt").write_text("LIST-THEN-READ\n", encoding="utf-8")
    list_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.list",
        arguments={"path": "materials"},
        created_at=_created_at(),
    )
    read_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "materials/brief.txt"},
        created_at=_created_at(),
    )

    result = run_local_harness(
        prompt="Discover and read the material.",
        title="Runtime list and read test",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=tuple(
                ScriptedModelResponse(completion=completion)
                for completion in (
                    _completion("Listing.", list_call),
                    _completion("Reading.", read_call),
                    _completion("Found LIST-THEN-READ."),
                )
            )
        ),
    )

    executed = [
        event.payload["tool_name"]
        for event in result.events
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
    ]
    assert executed == ["files.list", "files.read"]
    assert result.attempt_result.metadata["assistant_message"] == "Found LIST-THEN-READ."


def test_run_local_harness_lists_then_reads_configured_skill(tmp_path) -> None:
    skill_root = tmp_path / "skills"
    skill = skill_root / "evidence"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: evidence\ndescription: Collect evidence.\n---\n\nSKILL-PROOF-127\n",
        encoding="utf-8",
    )
    result = run_local_harness(
        prompt="Discover and read the evidence workflow.",
        title="Runtime Skill test",
        workspace_root=tmp_path.resolve(),
        skill_roots=(str(skill_root.resolve()),),
        model_gateway=ScriptedModelGateway(
            responses=tuple(
                ScriptedModelResponse(completion=completion)
                for completion in (
                    _completion(
                        "Listing Skills.",
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="skills.list",
                            arguments={},
                            created_at=_created_at(),
                        ),
                    ),
                    _completion(
                        "Reading evidence.",
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="skills.read",
                            arguments={"name": "evidence"},
                            created_at=_created_at(),
                        ),
                    ),
                    _completion("Used SKILL-PROOF-127."),
                )
            )
        ),
    )

    executed = [
        event.payload["tool_name"]
        for event in result.events
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
    ]
    assert executed == ["skills.list", "skills.read"]
    assert result.attempt_result.metadata["assistant_message"] == "Used SKILL-PROOF-127."


def test_run_local_harness_recalls_prior_session_then_synthesizes_answer(tmp_path) -> None:
    gateway = ScriptedModelGateway(
        responses=tuple(
            ScriptedModelResponse(completion=completion)
            for completion in (
                _completion(
                    "Searching prior sessions.",
                    ToolCall(
                        tool_call_id=new_tool_call_id(),
                        name="sessions.search",
                        arguments={"query": "continuity proof"},
                        created_at=_created_at(),
                    ),
                ),
                _completion("Recovered HISTORY-RECALL-PROOF."),
            )
        )
    )

    result = run_local_harness(
        prompt="Recover the continuity proof from a prior session.",
        title="Runtime session recall test",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
        session_history=ProofHistory(),
    )

    assert result.attempt_result.metadata["tool_name"] == "sessions.search"
    assert result.attempt_result.metadata["assistant_message"] == (
        "Recovered HISTORY-RECALL-PROOF."
    )
    tool_message = gateway.requests[1][-1]
    assert tool_message.role is MessageRole.TOOL
    assert "[UNTRUSTED HISTORICAL SESSION DATA]" in tool_message.content
    assert "HISTORY-RECALL-PROOF" in tool_message.content


def test_run_local_harness_injects_confirmed_memory_into_system_prompt(tmp_path) -> None:
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Repository summary.",
                        created_at=_created_at(),
                    )
                )
            ),
        )
    )

    run_local_harness(
        prompt="Summarize the repository.",
        title="Runtime memory prompt test",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
        confirmed_memories=(
            ConfirmedMemoryInput(
                memory_type=MemoryType.PROCEDURE,
                text="Run make check before push.",
            ),
        ),
    )

    assert gateway.requests[0][0].role is MessageRole.SYSTEM
    assert "Procedure 1" in gateway.requests[0][0].content
    assert "Run make check before push." in gateway.requests[0][0].content


def test_run_local_harness_advertises_its_executable_tools(tmp_path) -> None:
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="No tool needed.",
                        created_at=_created_at(),
                    )
                )
            ),
        )
    )

    run_local_harness(
        prompt="Inspect the workspace.",
        title="Runtime tool discovery test",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    tools = gateway.tool_requests[0]
    assert tuple(tool.name for tool in tools) == (
        "agent.clarify",
        "agent.plan",
        "agent.research",
        "command.run",
        "files.list",
        "files.read",
        "files.search",
        "patch.apply",
        "web.fetch",
    )
    file_read = next(tool for tool in tools if tool.name == "files.read")
    assert file_read.parameters["required"] == ["path"]


def test_local_tool_gateway_rejects_legacy_transports_when_v2_enabled(tmp_path) -> None:
    with pytest.raises(
        ValueError, match="legacy web transports are not supported when web_pipeline_v2 is enabled"
    ):
        LocalToolGateway(
            tmp_path.resolve(),
            web_pipeline_v2=True,
            web_gateway_transport=LocalWebGatewayTransport(),
        )
    with pytest.raises(
        ValueError, match="legacy web transports are not supported when web_pipeline_v2 is enabled"
    ):
        LocalToolGateway(
            tmp_path.resolve(),
            web_pipeline_v2=True,
            web_search_transport=LocalWebSearchTransport(),
        )
    with pytest.raises(
        ValueError,
        match="web_search_endpoint is not a valid web target for web_pipeline_v2",
    ):
        LocalToolGateway(
            tmp_path.resolve(),
            web_pipeline_v2=True,
            web_search_endpoint="http://search.example.com/search",
        )


def test_run_local_harness_rejects_invalid_web_search_endpoint_when_v2_enabled(tmp_path) -> None:
    with pytest.raises(
        ValueError,
        match="web_search_endpoint is not a valid web target for web_pipeline_v2",
    ):
        run_local_harness(
            prompt="Check search capabilities.",
            title="Invalid v2 endpoint should fail fast",
            workspace_root=tmp_path.resolve(),
            web_search_endpoint="http://search.example.com/search",
            web_pipeline_v2=True,
            model_gateway=ScriptedModelGateway(
                responses=(ScriptedModelResponse(completion=_completion("done")),)
            ),
        )


def test_local_tool_gateway_exposes_only_parallel_safe_builtins(tmp_path) -> None:
    gateway = LocalToolGateway(tmp_path.resolve())

    assert gateway.parallel_safe_tools == frozenset(
        {"files.list", "files.read", "files.search"}
    )


def test_local_tool_gateway_persists_complete_file_before_bounded_projection(tmp_path) -> None:
    content = "HEAD\n" + "x" * 20_000 + "\nTAIL"
    (tmp_path / "large.txt").write_text(content, encoding="utf-8")
    store = SQLiteArtifactPayloadStore(tmp_path / "sessions.sqlite")
    gateway = LocalToolGateway(
        tmp_path.resolve(),
        current_session_id="b678bd4d-c5e3-44d6-b49d-68fe33a041dc",
        artifact_payload_store=store,
    )

    result = gateway.execute(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="files.read",
            arguments={"path": "large.txt"},
            created_at=_created_at(),
        )
    )

    assert "HEAD" in result.output
    assert "TAIL" in result.output
    assert "middle omitted" in result.output
    envelope = result.metadata["output_envelope"]
    assert isinstance(envelope, dict)
    assert envelope["artifact_uri"] == result.metadata["artifact_uri"]
    stored = next((tmp_path / "sessions-artifacts").rglob("*.txt"))
    assert stored.read_text(encoding="utf-8") == content


def test_local_tool_gateway_registers_search_only_with_valid_configuration(tmp_path) -> None:
    unavailable = LocalToolGateway(tmp_path.resolve())
    malformed = LocalToolGateway(
        tmp_path.resolve(), web_search_endpoint="http://search.example.com"
    )
    configured = LocalToolGateway(
        tmp_path.resolve(), web_search_endpoint="https://search.example.com/search"
    )

    assert "web.search" not in {tool.name for tool in unavailable.model_tools}
    assert "web.search" not in {tool.name for tool in malformed.model_tools}
    assert "web.search" in {tool.name for tool in configured.model_tools}


def test_local_tool_gateway_can_disable_one_mcp_tool_without_affecting_web_search(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMcpTransport:
        model_tools = (
            ModelToolDefinition(
                name="mcp.minimax.understand_image",
                description="Legacy image understanding.",
                parameters={"type": "object", "properties": {}},
            ),
            ModelToolDefinition(
                name="mcp.fixture.echo",
                description="Echo input.",
                parameters={"type": "object", "properties": {}},
            ),
        )

    transport = FakeMcpTransport()
    monkeypatch.setattr(
        "agent_runtime.harness.build_mcp_transport",
        lambda *_args, **_kwargs: transport,
    )
    default = LocalToolGateway(
        tmp_path / "default",
        web_search_endpoint="https://search.example.com/search",
    )
    disabled = LocalToolGateway(
        tmp_path / "disabled",
        web_search_endpoint="https://search.example.com/search",
        disabled_mcp_tools=("mcp.minimax.understand_image",),
    )
    disabled_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="mcp.minimax.understand_image",
        arguments={},
        created_at=_created_at(),
    )

    assert "mcp.minimax.understand_image" in {
        tool.name for tool in default.effective_mcp_tools
    }
    assert "mcp.minimax.understand_image" not in {
        tool.name for tool in disabled.effective_mcp_tools
    }
    assert "web.search" in {tool.name for tool in disabled.model_tools}
    assert disabled.execute(disabled_call).status is ToolCallStatus.FAILED
    with pytest.raises(ValueError, match="unavailable"):
        disabled.resolve_model_tool_calls((disabled_call,))


def test_run_local_harness_narrows_preapproval_to_effective_mcp_tools(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_tool = "mcp.minimax.understand_image"
    search_tool = "mcp.minimax.web_search"

    class FakeMcpTransport:
        model_tools = (
            ModelToolDefinition(
                name=image_tool,
                description="Legacy image understanding.",
                parameters={"type": "object", "properties": {}},
            ),
            ModelToolDefinition(
                name=search_tool,
                description="Search the web.",
                parameters={"type": "object", "properties": {}},
            ),
        )

    captured: list[dict[str, object]] = []

    def build_policy(**kwargs):
        captured.append(kwargs)
        return LocalPolicyEngine(**kwargs)

    monkeypatch.setattr(
        "agent_runtime.harness.build_mcp_transport",
        lambda *_args, **_kwargs: FakeMcpTransport(),
    )
    monkeypatch.setattr("agent_runtime.harness.LocalPolicyEngine", build_policy)

    result = run_local_harness(
        prompt="Review the image and search for context.",
        title="Native media authority",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Review complete.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        ),
        policy_profile=PolicyProfile.READ_ONLY,
        network_profile=parse_network_profile("mcp-proxy-only"),
        mcp_servers=(McpServerSettings(name="minimax", command=sys.executable),),
        mcp_allowlist=(image_tool, search_tool),
        disabled_mcp_tools=(image_tool,),
        preapproved_readonly_tools=(image_tool, search_tool),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert captured[0]["mcp_allowlist"] == (search_tool,)
    assert captured[0]["preapproved_readonly_tools"] == (search_tool,)


def test_local_tool_gateway_registers_skills_only_with_configured_roots(tmp_path) -> None:
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    unavailable = LocalToolGateway(tmp_path.resolve())
    configured = LocalToolGateway(
        tmp_path.resolve(), skill_roots=(str(skill_root.resolve()),)
    )

    assert not {"skills.list", "skills.read"} & {
        tool.name for tool in unavailable.model_tools
    }
    assert {"skills.list", "skills.read"} <= {
        tool.name for tool in configured.model_tools
    }
    assert {"skills.list", "skills.read"} <= configured.parallel_safe_tools


@pytest.mark.parametrize("tool_profile", list(ToolProfile))
def test_local_tool_gateway_registers_session_history_only_with_port(
    tmp_path, tool_profile: ToolProfile
) -> None:
    unavailable = LocalToolGateway(tmp_path.resolve())
    configured = LocalToolGateway(
        tmp_path.resolve(),
        tool_profile=tool_profile,
        session_history=EmptyHistory(),
    )

    assert "sessions.search" not in {tool.name for tool in unavailable.model_tools}
    assert "sessions.search" in {tool.name for tool in configured.model_tools}
    assert "sessions.search" in configured.parallel_safe_tools


def test_local_tool_gateway_exposes_coding_profile_tools(tmp_path) -> None:
    gateway = LocalToolGateway(tmp_path.resolve(), tool_profile=ToolProfile.CODING)

    assert tuple(tool.name for tool in gateway.model_tools) == (
        "agent.clarify",
        "agent.plan",
        "command.run",
        "files.list",
        "files.read",
        "files.search",
        "git.status",
        "patch.apply",
        "tests.run",
        "web.fetch",
    )
    assert gateway.parallel_safe_tools == frozenset(
        {"files.list", "files.read", "files.search", "git.status"}
    )


def test_local_tool_gateway_registers_native_web_tools_when_v2_enabled(tmp_path) -> None:
    gateway = LocalToolGateway(tmp_path.resolve(), web_pipeline_v2=True)

    names = {tool.name for tool in gateway.model_tools}
    assert {"web.fetch", "web.crawl", "web.extract", "web.read", "web.find"} <= names


def test_local_tool_gateway_keeps_legacy_web_when_v2_disabled(tmp_path) -> None:
    gateway = LocalToolGateway(tmp_path.resolve())

    names = {tool.name for tool in gateway.model_tools}
    assert "web.fetch" in names
    assert "web.crawl" not in names
    assert "web.read" not in names


def test_local_tool_gateway_rejects_unknown_tool_profile(tmp_path) -> None:
    with pytest.raises(ValueError, match="tool_profile"):
        LocalToolGateway(tmp_path.resolve(), tool_profile="unknown")  # type: ignore[arg-type]


def test_local_tool_gateway_bounds_parallel_research_children(tmp_path) -> None:
    gateway = LocalToolGateway(
        tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Unused response.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        ),
    )
    try:
        assert "agent.research" in gateway.parallel_safe_tools
        assert gateway.parallel_batch_limits == {"agent.research": 3}
    finally:
        gateway.close()


def _created_at() -> datetime:
    return datetime(2026, 6, 22, 13, 0, tzinfo=UTC)


def _completion(content: str, *tool_calls: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=_created_at(),
        ),
        tool_calls=tool_calls,
    )
