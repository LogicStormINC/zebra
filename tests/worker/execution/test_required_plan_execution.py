from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_storage import SQLiteAgentTaskStore
from worker_execution_support import (
    _build_execution_service,
    _created_at,
    _seed_ready_session_with_input,
)


def test_worker_fails_required_plan_task_instead_of_completing(tmp_path, monkeypatch) -> None:
    database = tmp_path / "worker.sqlite"
    session_id = _seed_ready_session_with_input(
        database,
        tmp_path,
        user_input="Investigate a durable goal.",
        plan_required=True,
    )
    gateway = ScriptedModelGateway(
        responses=(_final("Done without a Plan."), _final("Still no Plan."))
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda settings: gateway
    )

    result = _build_execution_service(database).execute_session(
        session_id,
        worker_id="required-plan-worker",
        executed_at=_created_at(),
    )

    assert SQLiteAgentTaskStore(database).ensure_for_session(session_id).plan_required is True
    assert result.session.status is SessionStatus.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "required_plan_not_created"
    assert EventType.SESSION_COMPLETED not in {event.event_type for event in result.events}


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
