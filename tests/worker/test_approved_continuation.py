import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from agent_tools.mcp_disclosure import MCP_TOOL_CALL_NAME
from agent_tools.web_gateway import WebGatewayRequest, WebGatewayResponse
from agent_tools.web_search import (
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
)
from zebra_agent_api import create_app
from zebra_agent_config import (
    ApiSettings,
    McpServerSettings,
    ModelSettings,
    ZebraAgentSettings,
)
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
    WorkerExecutionError,
)
from zebra_agent_worker.approved_continuation import (
    ApprovedContinuationError,
    recover_approved_continuation,
)


class RecordingWebTransport:
    def __init__(self) -> None:
        self.requests: list[WebGatewayRequest] = []

    def execute(self, request: WebGatewayRequest) -> WebGatewayResponse:
        self.requests.append(request)
        return WebGatewayResponse(
            text="approved-web-output",
            status_code=200,
            content_type="text/plain",
            byte_count=19,
        )


class RecordingSearchTransport:
    def __init__(self) -> None:
        self.requests: list[WebSearchRequest] = []

    def execute(self, request: WebSearchRequest) -> WebSearchResponse:
        self.requests.append(request)
        return WebSearchResponse(
            results=(
                WebSearchResult(
                    title="Approved result",
                    url="https://docs.example.com/result",
                    snippet="approved-search-output",
                ),
            ),
            provider="searxng",
            byte_count=128,
        )


def test_granted_tool_call_resumes_exactly_once_without_reproposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "continuation.sqlite"
    created_at = datetime(2026, 7, 14, 7, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": [sys.executable, "-c", "print('approved-output')"]},
        created_at=created_at,
        provider_call_id="call_approved",
    )
    initial_gateway = _gateway("Running approved command.", tool_call=tool_call)
    final_gateway = _gateway("approved-output")
    gateways = iter((initial_gateway, final_gateway))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(database_path, tmp_path)
    service = _execution_service(database_path)

    waiting = service.execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=created_at,
    )

    assert waiting.session.status is SessionStatus.WAITING_APPROVAL
    approval = create_app(database_path, settings=_settings(database_path)).get_approval(
        str(session_id)
    )
    assert approval.body["approval_context"]["arguments"] == tool_call.arguments
    assert approval.body["approval_context"]["tool_call_id"] == str(tool_call.tool_call_id)
    decision = create_app(database_path, settings=_settings(database_path)).approve(
        str(session_id),
        {"operator": "tester", "reason": "approved exact call"},
    )
    assert decision.body["status"] == SessionStatus.RUNNING.value

    completed = service.execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=created_at,
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == "approved-output"
    assert len(initial_gateway.requests) == 1
    assert len(final_gateway.requests) == 1
    assert final_gateway.tool_requests[0]
    assert [message.role for message in final_gateway.requests[0]][-3:] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    assert final_gateway.requests[0][-1].content.strip() == "approved-output"
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert sum(event.event_type is EventType.TOOL_EXECUTION_STARTED for event in events) == 1
    with pytest.raises(SessionResumeError, match="terminal session"):
        service.execute_session(session_id, worker_id="worker-a", executed_at=created_at)


def test_web_gateway_waits_for_approval_then_executes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "web-continuation.sqlite"
    created_at = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.fetch",
        arguments={"url": "https://docs.example.com/guide"},
        created_at=created_at,
        provider_call_id="call_web_approved",
    )
    initial_gateway = _gateway("Reading approved Web content.", tool_call=tool_call)
    final_gateway = _gateway("approved-web-output")
    gateways = iter((initial_gateway, final_gateway))
    transport = RecordingWebTransport()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    monkeypatch.setattr(
        "agent_runtime.harness.LocalWebGatewayTransport",
        lambda: transport,
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        network_profile="domain-allowlist",
        network_allowlist=("docs.example.com",),
    )
    service = _execution_service(database_path)

    waiting = service.execute_session(
        session_id, worker_id="worker-web", executed_at=created_at
    )

    assert waiting.session.status is SessionStatus.WAITING_APPROVAL
    assert transport.requests == []
    approval = create_app(database_path, settings=_settings(database_path)).get_approval(
        str(session_id)
    )
    assert approval.body["approval_context"]["route"] == "web_gateway"
    assert approval.body["approval_context"]["target"] == "docs.example.com"
    create_app(database_path, settings=_settings(database_path)).approve(
        str(session_id),
        {"operator": "tester", "reason": "approved bounded Web read"},
    )

    completed = service.execute_session(
        session_id, worker_id="worker-web", executed_at=created_at
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == "approved-web-output"
    assert len(transport.requests) == 1
    assert transport.requests[0].target.hostname == "docs.example.com"
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert sum(
        event.event_type is EventType.TOOL_EXECUTION_STARTED
        and event.payload.get("tool_name") == "web.fetch"
        for event in events
    ) == 1


def test_mcp_stdio_waits_for_approval_then_recovers_exact_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "mcp-continuation.sqlite"
    marker = tmp_path / "mcp-called"
    created_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="mcp.fixture.echo",
        arguments={"value": "approved-mcp"},
        created_at=created_at,
        provider_call_id="call_mcp_approved",
    )
    gateways = iter(
        (
            _gateway("Calling configured MCP tool.", tool_call=tool_call),
            _gateway("approved-mcp-complete"),
        )
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    server_script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    settings = _settings(
        database_path,
        mcp_servers=(
            McpServerSettings(
                name="fixture",
                command=sys.executable,
                args=(str(server_script), "normal", str(marker)),
            ),
        ),
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        network_profile="mcp-proxy-only",
        mcp_allowlist=("mcp.fixture.echo",),
    )
    service = _execution_service(database_path, settings=settings)

    waiting = service.execute_session(session_id, worker_id="worker-mcp", executed_at=created_at)

    assert waiting.session.status is SessionStatus.WAITING_APPROVAL
    assert not marker.exists()
    approval = create_app(database_path, settings=settings).get_approval(str(session_id))
    assert approval.body["approval_context"]["target"] == "fixture.echo"
    create_app(database_path, settings=settings).approve(
        str(session_id),
        {"operator": "tester", "reason": "approved exact MCP call"},
    )

    completed = service.execute_session(
        session_id, worker_id="worker-mcp", executed_at=created_at
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == "approved-mcp-complete"
    assert marker.read_text(encoding="utf-8") == "called"
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert sum(
        event.event_type is EventType.TOOL_EXECUTION_STARTED
        and event.payload.get("tool_name") == "mcp.fixture.echo"
        for event in events
    ) == 1


def test_large_mcp_catalog_bridge_waits_for_approval_then_recovers_provider_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "mcp-bridge-continuation.sqlite"
    marker = tmp_path / "mcp-bridge-called"
    created_at = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name=MCP_TOOL_CALL_NAME,
        arguments={
            "name": "mcp.fixture.echo",
            "arguments": {"value": "approved-bridge"},
        },
        created_at=created_at,
        provider_call_id="call_mcp_bridge",
    )
    final_gateway = _gateway("approved-mcp-bridge-complete")
    gateways = iter(
        (
            _gateway("Calling selected MCP tool through bridge.", tool_call=tool_call),
            final_gateway,
        )
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    server_script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    settings = _settings(
        database_path,
        mcp_servers=(
            McpServerSettings(
                name="fixture",
                command=sys.executable,
                args=(str(server_script), "large-catalog", str(marker)),
            ),
        ),
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        network_profile="mcp-proxy-only",
        mcp_allowlist=tuple(
            f"mcp.fixture.echo{index if index else ''}" for index in range(16)
        ),
    )
    service = _execution_service(database_path, settings=settings)

    waiting = service.execute_session(
        session_id,
        worker_id="worker-mcp-bridge",
        executed_at=created_at,
    )

    assert waiting.session.status is SessionStatus.WAITING_APPROVAL
    assert not marker.exists()
    approval = create_app(database_path, settings=settings).get_approval(str(session_id))
    context = approval.body["approval_context"]
    assert context["tool_name"] == "mcp.fixture.echo"
    assert context["provider_tool_name"] == MCP_TOOL_CALL_NAME
    assert context["provider_arguments"] == tool_call.arguments
    create_app(database_path, settings=settings).approve(
        str(session_id),
        {"operator": "tester", "reason": "approved bridged MCP call"},
    )

    completed = service.execute_session(
        session_id,
        worker_id="worker-mcp-bridge",
        executed_at=created_at,
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert marker.read_text(encoding="utf-8") == "called"
    resumed_call = final_gateway.requests[0][-2].tool_calls[0]
    assert resumed_call.name == "mcp.fixture.echo"
    assert resumed_call.provider_tool_name == MCP_TOOL_CALL_NAME
    assert resumed_call.provider_arguments == tool_call.arguments
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert sum(
        event.event_type is EventType.TOOL_EXECUTION_STARTED
        and event.payload.get("tool_name") == "mcp.fixture.echo"
        for event in events
    ) == 1


def test_mcp_recovery_fails_closed_when_selected_server_was_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "mcp-removed.sqlite"
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _gateway("unused"),
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        network_profile="mcp-proxy-only",
        mcp_allowlist=("mcp.fixture.echo",),
    )

    with pytest.raises(WorkerExecutionError, match="unavailable"):
        _execution_service(
            database_path,
            settings=_settings(database_path),
        ).execute_session(session_id, worker_id="worker-mcp-removed")
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert sum(
        event.event_type is EventType.TOOL_EXECUTION_STARTED
        and event.payload.get("tool_name") == "mcp.fixture.echo"
        for event in events
    ) == 0


def test_web_search_waits_for_approval_then_executes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "search-continuation.sqlite"
    created_at = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.search",
        arguments={"query": "zebra agent", "limit": 2},
        created_at=created_at,
        provider_call_id="call_search_approved",
    )
    gateways = iter(
        (
            _gateway("Searching approved sources.", tool_call=tool_call),
            _gateway("approved-search-output"),
        )
    )
    transport = RecordingSearchTransport()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    monkeypatch.setattr(
        "agent_runtime.harness.LocalWebSearchTransport",
        lambda: transport,
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        network_profile="domain-allowlist",
        network_allowlist=("search.example.com",),
    )
    settings = _settings(
        database_path,
        web_search_endpoint="https://search.example.com/search",
    )
    service = _execution_service(database_path, settings=settings)

    waiting = service.execute_session(
        session_id, worker_id="worker-search", executed_at=created_at
    )

    assert waiting.session.status is SessionStatus.WAITING_APPROVAL
    assert transport.requests == []
    app = create_app(database_path, settings=settings)
    approval = app.get_approval(str(session_id))
    context = approval.body["approval_context"]
    assert context["target"] == "search.example.com"
    assert context["scope"][-3:] == [
        "query:zebra agent",
        "limit:2",
        "side_effect:read_only",
    ]
    app.approve(
        str(session_id),
        {"operator": "tester", "reason": "approved bounded Web search"},
    )

    completed = service.execute_session(
        session_id, worker_id="worker-search", executed_at=created_at
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert len(transport.requests) == 1
    assert transport.requests[0].query == "zebra agent"
    assert transport.requests[0].endpoint.hostname == "search.example.com"


def test_approved_continuation_does_not_replay_uncertain_execution() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 7, 14, 7, 30, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
            created_at=created_at,
        )
        for sequence, event_type, actor, payload in (
            (
                0,
                EventType.APPROVAL_REQUESTED,
                EventActor.POLICY,
                {"tool_call_id": "pending", "call_fingerprint": "fingerprint"},
            ),
            (
                1,
                EventType.APPROVAL_GRANTED,
                EventActor.USER,
                {"tool_call_id": "pending", "call_fingerprint": "fingerprint"},
            ),
            (2, EventType.TOOL_EXECUTION_STARTED, EventActor.HARNESS, {}),
        )
    ]

    with pytest.raises(ApprovedContinuationError, match="uncertain prior execution"):
        recover_approved_continuation(events)


def test_later_approved_tool_resumes_with_prior_tool_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "later-continuation.sqlite"
    created_at = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    (tmp_path / "proof.txt").write_text("prior-result", encoding="utf-8")
    read_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "proof.txt"},
        created_at=created_at,
        provider_call_id="call_read",
    )
    command_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": [sys.executable, "-c", "print('later-approved')"]},
        created_at=created_at,
        provider_call_id="call_command",
    )
    initial_gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Read proof first.",
                        created_at=created_at,
                    ),
                    tool_calls=(read_call,),
                )
            ),
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Run the follow-up command.",
                        created_at=created_at,
                    ),
                    tool_calls=(command_call,),
                )
            ),
        )
    )
    final_gateway = _gateway("prior-result and later-approved")
    gateways = iter((initial_gateway, final_gateway))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(database_path, tmp_path)
    service = _execution_service(database_path)

    waiting = service.execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=created_at,
    )

    assert waiting.session.status is SessionStatus.WAITING_APPROVAL
    assert waiting.attempt_result.metadata["tool_calls_executed"] == 1
    approval_event = next(
        event
        for event in reversed(SQLiteEventStore(database_path).list_for_session(session_id))
        if event.event_type is EventType.APPROVAL_REQUESTED
    )
    assert approval_event.payload["model_calls_used"] == 2
    assert approval_event.payload["tool_calls_executed"] == 1
    assert [item["role"] for item in approval_event.payload["conversation"]][-3:] == [
        "assistant",
        "tool",
        "assistant",
    ]

    create_app(database_path, settings=_settings(database_path)).approve(
        str(session_id),
        {"operator": "tester", "reason": "approve later call"},
    )
    completed = service.execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=created_at,
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == (
        "prior-result and later-approved"
    )
    assert completed.attempt_result.metadata["model_calls_used"] == 3
    assert completed.attempt_result.metadata["tool_calls_executed"] == 2
    final_messages = final_gateway.requests[0]
    assert [message.role for message in final_messages][-4:] == [
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    started_names = [
        event.payload.get("tool_name")
        for event in events
        if event.event_type is EventType.TOOL_EXECUTION_STARTED
    ]
    assert started_names == ["files.read", "command.run"]


def _gateway(content: str, *, tool_call: ToolCall | None = None) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content=content,
                        created_at=datetime(2026, 7, 14, 7, 0, tzinfo=UTC),
                    ),
                    tool_calls=(tool_call,) if tool_call is not None else (),
                )
            ),
        )
    )


def _seed_session(
    database_path: Path,
    workspace_root: Path,
    *,
    network_profile: str = "none",
    network_allowlist: tuple[str, ...] = (),
    mcp_allowlist: tuple[str, ...] = (),
):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Approved continuation",
            user_input="Run the approved command.",
            workspace_root=workspace_root.resolve(),
            policy_profile="workspace_write",
            network_profile=network_profile,
            network_allowlist=network_allowlist,
            mcp_allowlist=mcp_allowlist,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    return bootstrap.session.session_id


def _execution_service(
    database_path: Path,
    *,
    settings: ZebraAgentSettings | None = None,
) -> SessionExecutionService:
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    return SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=settings or _settings(database_path),
    )


def _settings(
    database_path: Path,
    *,
    web_search_endpoint: str | None = None,
    mcp_servers: tuple[McpServerSettings, ...] = (),
) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        web_search_endpoint=web_search_endpoint,
        mcp_servers=mcp_servers,
    )
