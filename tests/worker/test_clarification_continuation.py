from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.ports.model_gateway import ModelGatewayPort, ModelResponseRejectedError
from agent_storage import (
    FinosJournalGrant,
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteFinosJournalGrantStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api import create_app
from zebra_agent_config import (
    ApiSettings,
    FinosJournalProviderSettings,
    ModelSettings,
    ZebraAgentSettings,
)
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


class _PolicyAwareScriptedGateway(ScriptedModelGateway):
    def complete_with_policy(
        self,
        messages,
        *,
        tools=(),
        media_inputs=(),
        invocation_policy=None,
    ):
        del media_inputs, invocation_policy
        return self.complete(messages, tools=tools)


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
    plan_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.plan",
        arguments={
            "steps": [
                {
                    "step_id": "audience",
                    "content": "Resolve the target audience",
                    "status": "in_progress",
                },
                {
                    "step_id": "summary",
                    "content": "Produce the evidence-backed summary",
                    "status": "pending",
                },
            ]
        },
        created_at=NOW,
    )
    read_plan_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.plan",
        arguments={},
        created_at=NOW,
    )
    close_plan_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.plan",
        arguments={
            "steps": [
                {
                    "step_id": "audience",
                    "content": "Resolve the target audience",
                    "status": "completed",
                },
                {
                    "step_id": "summary",
                    "content": "Produce the evidence-backed summary",
                    "status": "completed",
                },
            ]
        },
        created_at=NOW,
    )
    initial_gateway = ScriptedModelGateway(
        responses=(
            _response("I will track the remaining work.", plan_call),
            _response("I need one decision.", clarify_call),
        )
    )
    final_gateway = ScriptedModelGateway(
        responses=(
            _response("I will restore the current plan.", read_plan_call),
            _response("I have finished the remaining work.", close_plan_call),
            _response("I will prioritize operators."),
            _response("I will prioritize operators."),
        )
    )
    gateways = iter((initial_gateway, final_gateway))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(database_path, tmp_path)
    service = _execution_service(database_path)

    waiting = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)
    waiting_task = SQLiteAgentTaskStore(database_path).ensure_for_session(session_id)
    response = create_app(database_path).append_session_message(
        str(session_id),
        {
            "content": "Operators",
            "clarification_id": str(clarify_call.tool_call_id),
        },
    )
    completed = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)

    assert waiting.session.status is SessionStatus.WAITING_INPUT
    assert waiting_task.goal == "Prepare an audience-specific summary."
    assert waiting_task.task_plan.summary == {
        "pending": 1,
        "in_progress": 1,
        "completed": 0,
        "cancelled": 0,
        "total": 2,
    }
    assert response.status_code == 201
    assert response.body["clarification_resolved"] is True
    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == (
        "I will prioritize operators."
    )
    assert len(initial_gateway.requests) == 2
    assert len(final_gateway.requests) == 4
    assert final_gateway.requests[0][-1].role is MessageRole.TOOL
    assert '"user_response":"Operators"' in final_gateway.requests[0][-1].content
    restored_plan = final_gateway.requests[1][-1]
    assert restored_plan.role is MessageRole.TOOL
    assert '"status":"in_progress"' in restored_plan.content
    assert '"status":"pending"' in restored_plan.content
    completed_task = SQLiteAgentTaskStore(database_path).ensure_for_session(session_id)
    assert completed_task.goal == waiting_task.goal
    assert completed_task.task_plan.summary["completed"] == 2
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


def test_required_plan_nudge_remains_bounded_across_clarification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "required-plan-clarification.sqlite"
    first_read = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "first.txt"},
        created_at=NOW,
    )
    clarify_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={"question": "Which account?"},
        created_at=NOW,
    )
    second_read = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "second.txt"},
        created_at=NOW,
    )
    initial = ScriptedModelGateway(
        responses=(
            _response("Read before planning.", first_read),
            _response("I need one answer.", clarify_call),
        )
    )
    resumed = ScriptedModelGateway(
        responses=(_response("Read before planning again.", second_read),)
    )
    gateways = iter((initial, resumed))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        plan_required=True,
    )
    service = _execution_service(database_path)

    waiting = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)
    create_app(database_path).append_session_message(
        str(session_id),
        {
            "content": "Main account",
            "clarification_id": str(clarify_call.tool_call_id),
        },
    )
    failed = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)

    assert waiting.session.status is SessionStatus.WAITING_INPUT
    assert failed.session.status is SessionStatus.FAILED
    assert failed.attempt_result.metadata["stop_reason"] == "required_plan_not_created"
    assert len(resumed.requests) == 1
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert not any(
        event.event_type is EventType.TOOL_EXECUTION_STARTED
        and event.payload.get("tool_name") == "files.read"
        for event in events
    )


def test_completion_evidence_correction_remains_bounded_across_clarification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "completion-evidence-clarification.sqlite"
    clarify_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={"question": "Which account?"},
        created_at=NOW,
    )
    # Under the typed-tool-only contract the model asks its clarification on
    # the initial dispatch; the bounded evidence correction only runs after
    # the continuation, with the genuine advertised producer forced.
    initial = _PolicyAwareScriptedGateway(
        responses=(_response("I need one answer.", clarify_call),)
    )
    resumed = _PolicyAwareScriptedGateway(
        responses=(
            _response("Still no authoritative evidence."),
            _response("Still no authoritative evidence."),
            _response("Attempt 2 still no authoritative evidence."),
            _response("Attempt 2 still no authoritative evidence."),
        )
    )
    gateways = iter((initial, resumed))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        agent_definition=_authoritative_evidence_definition(),
        max_corrections_per_attempt=1,
        max_attempts=2,
    )
    task = SQLiteAgentTaskStore(database_path).ensure_for_session(session_id)
    SQLiteFinosJournalGrantStore(database_path).bind(
        FinosJournalGrant(
            task_id=task.task_id,
            contract_version="finos.journals.v1",
            grant="private-grant",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    service = _execution_service(database_path)

    waiting = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)
    create_app(database_path).append_session_message(
        str(session_id),
        {"content": "Main account", "clarification_id": str(clarify_call.tool_call_id)},
    )
    failed = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)

    assert waiting.session.status is SessionStatus.WAITING_INPUT
    assert failed.session.status is SessionStatus.FAILED
    assert failed.attempt_result.metadata["stop_reason"] == (
        "completion_evidence_missing_after_correction"
    )
    # Attempt 1 (resumed): completion + one typed correction; then the
    # retryable after-correction code schedules Attempt 2 with its own
    # completion + one typed correction before the terminal.
    assert len(resumed.requests) == 4
    assert sum(
        message.metadata.get("missing_completion_evidence") is not None
        for request in resumed.requests
        for message in request
        if message.role is MessageRole.SYSTEM
    ) == 2
    assert failed.attempt_result.metadata.get("stop_reason") != (
        "attempt_reconstruction_invalid"
    )
    starts = [
        event
        for event in SQLiteEventStore(database_path).list_for_session(session_id)
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in starts] == [1, 2]
    clarification = next(
        event
        for event in SQLiteEventStore(database_path).list_for_session(session_id)
        if event.event_type is EventType.CLARIFICATION_REQUESTED
    )
    assert sum(
        message.get("metadata", {}).get("missing_completion_evidence") is not None
        for message in clarification.payload["conversation"]
    ) == 0


def test_guarded_clarification_resumes_same_attempt_without_reconstruction_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "guarded-clarification.sqlite"
    clarify_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={"question": "Which account?"},
        created_at=NOW,
    )
    initial = ScriptedModelGateway(
        responses=(_response("I need one answer.", clarify_call),)
    )
    resumed = ScriptedModelGateway(
        responses=(_response("Done with the requested summary."),)
    )
    gateways = iter((initial, resumed))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: next(gateways),
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        max_attempts=2,
    )
    service = _execution_service(database_path)

    waiting = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)
    assert waiting.session.status is SessionStatus.WAITING_INPUT

    create_app(database_path).append_session_message(
        str(session_id),
        {"content": "Main account", "clarification_id": str(clarify_call.tool_call_id)},
    )
    completed = service.execute_session(session_id, worker_id="worker-a", executed_at=NOW)

    assert completed.session.status is SessionStatus.COMPLETED
    assert len(resumed.requests) == 1
    assert completed.attempt_result.metadata.get("stop_reason") != (
        "attempt_reconstruction_invalid"
    )
    starts = [
        event
        for event in SQLiteEventStore(database_path).list_for_session(session_id)
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in starts] == [1]


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
    return ScriptedModelGateway(responses=(_response(content, tool_call),))


def _response(content: str, tool_call: ToolCall | None = None) -> ScriptedModelResponse:
    return ScriptedModelResponse(
        completion=ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=content,
                created_at=NOW,
            ),
            tool_calls=(tool_call,) if tool_call is not None else (),
        )
    )


def _seed_session(
    database_path: Path,
    workspace_root: Path,
    *,
    plan_required: bool = False,
    agent_definition: AgentDefinition | None = None,
    max_corrections_per_attempt: int = 0,
    max_attempts: int = 1,
):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Clarification continuation",
            user_input="Prepare an audience-specific summary.",
            workspace_root=workspace_root.resolve(),
            policy_profile="workspace_write",
            plan_required=plan_required,
            agent_definition=agent_definition,
            max_corrections_per_attempt=max_corrections_per_attempt,
            max_attempts=max_attempts,
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


def _authoritative_evidence_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="finos",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="authoritative_financial_evidence",
                    typed_evidence=("authoritative_typed_read",),
                ),
            )
        ),
    )


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
            finos_journal_provider=FinosJournalProviderSettings(
                base_url="https://finos.internal"
            ),
            model=ModelSettings(
                provider="test",
                api_key_env="TEST_API_KEY",
                base_url="https://example.test",
                model="test-model",
            ),
        ),
    )
