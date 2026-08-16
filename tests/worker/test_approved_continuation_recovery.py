"""Recovery semantics for approved continuations with durably completed tools."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventActor, EventType, SessionEvent
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


def test_completed_tool_continuation_resumes_without_reexecution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A durably completed approved tool must never re-execute on recovery.

    Simulates the Worker dying between the fenced tool completion and the
    final model turn: recovery must continue from the recorded output
    instead of failing closed on uncertain state.
    """
    database_path = tmp_path / "completed-continuation.sqlite"
    created_at = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": [sys.executable, "-c", "print('recovered-output')"]},
        created_at=created_at,
        provider_call_id="call_completed",
    )
    initial_gateway = _gateway("Run once.", tool_call=tool_call)
    final_gateway = _gateway("recovered-output")
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
    assert (
        create_app(database_path, settings=_settings(database_path))
        .approve(
            str(session_id),
            {"operator": "tester", "reason": "approved exact call"},
        )
        .body["status"]
        == SessionStatus.RUNNING.value
    )

    event_store = SQLiteEventStore(database_path)
    events = event_store.list_for_session(session_id)
    requested = next(event for event in events if event.event_type is EventType.APPROVAL_REQUESTED)
    pending_id = requested.payload["tool_call_id"]
    sequence = events[-1].sequence
    for event_type, payload in (
        (
            EventType.TOOL_EXECUTION_STARTED,
            {
                "attempt_number": 1,
                "tool_name": "command.run",
                "tool_call_id": pending_id,
            },
        ),
        (
            EventType.TOOL_EXECUTION_COMPLETED,
            {
                "attempt_number": 1,
                "tool_name": "command.run",
                "tool_call_id": pending_id,
                "status": "executed",
                "output": "recovered-output",
                "metadata": {},
            },
        ),
    ):
        sequence += 1
        event_store.append(
            SessionEvent.create(
                session_id=session_id,
                sequence=sequence,
                event_type=event_type,
                actor=EventActor.HARNESS,
                payload=payload,
                created_at=created_at,
            )
        )

    completed = service.execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=created_at,
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == "recovered-output"
    assert len(final_gateway.requests) == 1
    assert [message.role for message in final_gateway.requests[0]][-2:] == [
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    assert final_gateway.requests[0][-1].content.strip() == "recovered-output"
    ledger = SQLiteEventStore(database_path).list_for_session(session_id)
    started_count = sum(event.event_type is EventType.TOOL_EXECUTION_STARTED for event in ledger)
    completed_count = sum(
        event.event_type is EventType.TOOL_EXECUTION_COMPLETED for event in ledger
    )
    assert started_count == 1
    assert completed_count == 1


def _gateway(
    content: str,
    *,
    tool_call: ToolCall | None = None,
) -> ScriptedModelGateway:
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
            network_profile="none",
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
