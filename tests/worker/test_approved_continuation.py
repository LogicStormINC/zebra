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
from zebra_agent_api import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
)
from zebra_agent_worker.approved_continuation import (
    ApprovedContinuationError,
    recover_approved_continuation,
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
    assert approval.body["approval_context"]["tool_call_id"] == str(
        tool_call.tool_call_id
    )
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
    assert final_gateway.tool_requests == ((),)
    assert [message.role for message in final_gateway.requests[0]][-4:] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.USER,
    ]
    assert final_gateway.requests[0][-2].content.strip() == "approved-output"
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert sum(event.event_type is EventType.TOOL_EXECUTION_STARTED for event in events) == 1
    with pytest.raises(SessionResumeError, match="terminal session"):
        service.execute_session(session_id, worker_id="worker-a", executed_at=created_at)


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


def _seed_session(database_path: Path, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Approved continuation",
            user_input="Run the approved command.",
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
