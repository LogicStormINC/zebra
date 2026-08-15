import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCallStatus
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from worker_execution_support import _build_execution_service, _created_at, _settings
from zebra_agent_api import RouteAdapter, RouteRequest, create_app


@pytest.mark.parametrize(
    "typed_evidence",
    ("authoritative_typed_read", "confirmed_investor_knowledge"),
)
def test_worker_rollover_reuses_prior_typed_evidence(
    tmp_path, monkeypatch, typed_evidence: str
) -> None:
    database = tmp_path / "worker.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Authoritative evidence",
            user_input="Review the authorized records.",
            workspace_root=tmp_path.resolve(),
            agent_definition=_definition(typed_evidence),
            created_at=_created_at(),
        )
    )
    root_id = bootstrap.session.session_id
    attempt_started = SessionEvent.create(
        session_id=root_id,
        sequence=3,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=_created_at(),
    )
    evidence = SessionEvent.create(
        session_id=root_id,
        sequence=4,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "finos.journals.list",
            "tool_call_id": str(new_tool_call_id()),
            "status": ToolCallStatus.EXECUTED.value,
            "output": "[]",
            "metadata": {"typed_evidence": [typed_evidence]},
        },
        created_at=_created_at(),
    )
    completed = SessionEvent.create(
        session_id=root_id,
        sequence=5,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"summary": "first segment completed"},
        created_at=_created_at(),
    )
    events = (*bootstrap.events, attempt_started, evidence, completed)
    event_store = SQLiteEventStore(database)
    for event in events:
        event_store.append(event)
    session = bootstrap.session
    for event in (attempt_started, evidence, completed):
        session = apply_event(session, event)
    SQLiteProjectionStore(database).save_session(session)
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(events))
    task_store = SQLiteAgentTaskStore(database)
    task = task_store.ensure_for_session(root_id)

    follow_up = RouteAdapter(create_app(database, settings=_settings(database))).handle(
        RouteRequest(
            "POST",
            f"/tasks/{task.task_id}/messages",
            body={"content": "Use the same evidence for the follow-up."},
        )
    )
    active = task_store.get_task(task.task_id)
    assert follow_up.status_code == 201
    assert active is not None
    assert active.active_segment_id != root_id

    gateway = ScriptedModelGateway(
        responses=(_final("The prior evidence remains sufficient."), _final("Unused."))
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda _settings: gateway
    )
    result = _build_execution_service(database).execute_session(
        active.active_segment_id,
        worker_id="evidence-worker",
        executed_at=_created_at(),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["completion_evidence_satisfied"] is True
    assert len(gateway.requests) == 2


def _definition(typed_evidence: str) -> AgentDefinition:
    return AgentDefinition(
        agent_id="finos",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="required_typed_evidence",
                    typed_evidence=(typed_evidence,),
                ),
            )
        ),
    )


def _final(content: str) -> ScriptedModelResponse:
    return ScriptedModelResponse(
        completion=ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=content,
                created_at=_created_at(),
            )
        )
    )
