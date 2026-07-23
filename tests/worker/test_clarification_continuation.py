from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.ports.model_gateway import ModelGatewayPort, ModelResponseRejectedError
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
from zebra_agent_worker.clarification_continuation import (
    ClarificationContinuationError,
    recover_clarification_continuation,
)

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


def test_clarification_response_resumes_same_session_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "clarification.sqlite"
    clarify_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={
            "question": "Which audience should I prioritize?",
            "choices": ["Operators", "Analysts"],
        },
        created_at=NOW,
        provider_call_id="call_clarify",
    )
    initial_gateway = _gateway("I need one decision.", clarify_call)
    final_gateway = _gateway("I will prioritize operators.")
    gateways = iter((initial_gateway, final_gateway))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(database_path, tmp_path)
    service = _execution_service(database_path)

    waiting = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)
    response = create_app(database_path).append_session_message(
        str(session_id),
        {
            "content": "Operators",
            "clarification_id": str(clarify_call.tool_call_id),
        },
    )
    completed = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)

    assert waiting.session.status is SessionStatus.WAITING_INPUT
    assert response.status_code == 201
    assert response.body["clarification_resolved"] is True
    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == (
        "I will prioritize operators."
    )
    assert len(initial_gateway.requests) == 1
    assert len(final_gateway.requests) == 1
    assert final_gateway.requests[0][-1].role is MessageRole.TOOL
    assert '"user_response":"Operators"' in final_gateway.requests[0][-1].content
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert sum(
        event.event_type is EventType.CLARIFICATION_REQUESTED for event in events
    ) == 1
    assert sum(
        event.event_type is EventType.CLARIFICATION_RESPONDED for event in events
    ) == 1
    assert sum(
        event.event_type is EventType.HARNESS_ATTEMPT_STARTED
        and event.payload.get("clarification_continuation") is True
        for event in events
    ) == 1


def test_clarification_continuation_fails_closed_after_start_marker() -> None:
    session_id = new_session_id()
    clarification_id = str(new_tool_call_id())
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
            created_at=NOW,
        )
        for sequence, event_type, actor, payload in (
            (
                0,
                EventType.CLARIFICATION_REQUESTED,
                EventActor.HARNESS,
                {
                    "attempt_number": 1,
                    "clarification_id": clarification_id,
                    "tool_call_id": clarification_id,
                    "question": "Which audience?",
                    "assistant_message": "I need one decision.",
                    "conversation": [],
                    "model_calls_used": 1,
                    "tool_calls_executed": 0,
                },
            ),
            (
                1,
                EventType.CLARIFICATION_RESPONDED,
                EventActor.USER,
                {
                    "clarification_id": clarification_id,
                    "content": "Operators",
                    "selected_choice": False,
                },
            ),
            (
                2,
                EventType.HARNESS_ATTEMPT_STARTED,
                EventActor.HARNESS,
                {"clarification_continuation": True},
            ),
        )
    ]

    with pytest.raises(ClarificationContinuationError, match="uncertain prior model-call"):
        recover_clarification_continuation(events)


def test_clarification_provider_failure_becomes_durable_terminal_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "provider-failure.sqlite"
    clarify_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={"question": "Which audience?"},
        created_at=NOW,
    )
    gateways: Iterator[ModelGatewayPort] = iter(
        (_gateway("I need one decision.", clarify_call), FailingModelGateway())
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(database_path, tmp_path)
    service = _execution_service(database_path)
    service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)
    response = create_app(database_path).append_session_message(
        str(session_id),
        {
            "content": "Operators",
            "clarification_id": str(clarify_call.tool_call_id),
        },
    )

    failed = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)

    assert response.status_code == 201
    assert failed.session.status is SessionStatus.FAILED
    assert failed.attempt_result.metadata["stop_reason"] == "model_execution_failed"
    assert failed.attempt_result.metadata["error_type"] == "ValueError"
    assert SQLiteLeaseStore(database_path).get(session_id) is None


def test_rejected_model_response_exhaustion_becomes_recoverable_suspension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "response-rejected.sqlite"
    gateway = RejectingModelGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )
    session_id = _seed_session(database_path, tmp_path)

    suspended = _execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=NOW,
    )

    assert gateway.calls == 2
    assert suspended.session.status is SessionStatus.SUSPENDED
    assert suspended.attempt_result.metadata["stop_reason"] == (
        "model_response_repair_exhausted"
    )
    assert suspended.attempt_result.metadata["response_repair_count"] == 1
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert any(event.event_type is EventType.SESSION_SUSPENDED for event in events)
    assert not any(event.event_type is EventType.SESSION_FAILED for event in events)


class FailingModelGateway(ModelGatewayPort):
    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        del messages, tools
        raise ValueError("provider body must not be persisted")


class RejectingModelGateway(ModelGatewayPort):
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        del messages, tools
        self.calls += 1
        raise ModelResponseRejectedError(
            "invalid_tool_arguments_json",
            phase="tool_arguments",
            retryable=True,
            provider_tool_name="files__write",
        )


def _gateway(content: str, tool_call: ToolCall | None = None) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content=content,
                        created_at=NOW,
                    ),
                    tool_calls=(tool_call,) if tool_call is not None else (),
                )
            ),
        )
    )


def _seed_session(database_path: Path, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Clarification continuation",
            user_input="Prepare an audience-specific summary.",
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
        settings=ZebraAgentSettings(
            profile="test",
            database_url=str(database_path),
            api=ApiSettings(auth_token=None),
            model=ModelSettings(
                provider="test",
                api_key_env="TEST_API_KEY",
                base_url="https://example.test",
                model="test-model",
            ),
        ),
    )
