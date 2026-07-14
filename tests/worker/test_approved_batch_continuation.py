import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
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
from zebra_agent_api import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)


def test_approved_batch_continues_tail_without_replaying_completed_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "batch-continuation.sqlite"
    created_at = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    (tmp_path / "first.txt").write_text("FIRST", encoding="utf-8")
    (tmp_path / "last.txt").write_text("LAST", encoding="utf-8")
    first = _call("files.read", {"path": "first.txt"}, "call_first", created_at)
    pending = _call(
        "command.run",
        {"command": [sys.executable, "-c", "print('APPROVED')"]},
        "call_pending",
        created_at,
    )
    tail = _call("files.read", {"path": "last.txt"}, "call_last", created_at)
    initial_gateway = _gateway(
        _completion("Run the complete batch.", created_at, first, pending, tail)
    )
    final_gateway = _gateway(_completion("FIRST|APPROVED|LAST", created_at))
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
    assert approval_event.payload["tool_call_id"] == str(pending.tool_call_id)
    assert approval_event.payload["remaining_tool_calls"] == [tail.model_dump(mode="json")]
    conversation = approval_event.payload["conversation"]
    assert [item["role"] for item in conversation][-2:] == ["assistant", "tool"]
    assert len(conversation[-2]["tool_calls"]) == 3

    create_app(database_path, settings=_settings(database_path)).approve(
        str(session_id),
        {"operator": "tester", "reason": "approve middle batch call"},
    )
    completed = service.execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=created_at,
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == ("FIRST|APPROVED|LAST")
    assert completed.attempt_result.metadata["model_calls_used"] == 2
    assert completed.attempt_result.metadata["tool_calls_executed"] == 3
    assert [
        draft.payload.get("tool_name")
        for draft in completed.attempt_result.emitted_events
        if draft.event_type is EventType.TOOL_EXECUTION_STARTED
    ] == ["files.read"]
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert [
        event.payload.get("tool_name")
        for event in events
        if event.event_type is EventType.TOOL_EXECUTION_STARTED
    ] == ["files.read", "command.run", "files.read"]
    final_messages = final_gateway.requests[0]
    assistant = next(
        message for message in reversed(final_messages) if message.role is MessageRole.ASSISTANT
    )
    assert assistant.tool_calls == (first, pending, tail)
    assert [
        message.tool_call_id for message in final_messages if message.role is MessageRole.TOOL
    ] == ["call_first", "call_pending", "call_last"]


def _call(
    name: str,
    arguments: dict[str, object],
    provider_id: str,
    created_at: datetime,
) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=created_at,
        provider_call_id=provider_id,
    )


def _completion(
    content: str,
    created_at: datetime,
    *tool_calls: ToolCall,
) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=created_at,
        ),
        tool_calls=tool_calls,
    )


def _gateway(completion: ModelCompletion) -> ScriptedModelGateway:
    return ScriptedModelGateway(responses=(ScriptedModelResponse(completion=completion),))


def _seed_session(database_path: Path, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Approved batch continuation",
            user_input="Run the requested batch.",
            workspace_root=workspace_root.resolve(),
            policy_profile="workspace_write",
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


def _execution_service(database_path: Path) -> SessionExecutionService:
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
        settings=_settings(database_path),
    )


def _settings(database_path: Path) -> ZebraAgentSettings:
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
    )
