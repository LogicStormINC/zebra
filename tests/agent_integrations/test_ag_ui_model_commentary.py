from datetime import UTC, datetime
from hashlib import sha256

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id
from agent_integrations.ag_ui import AgUiProjector, AgUiRunIdentity


def test_model_commentary_producer_plan_survives_ag_ui_projection() -> None:
    session_id = new_session_id()
    call, text = "model-commentary", "  正在核对两份来源。\n"
    plan = {
        "schema_version": 1,
        "disposition": "admitted",
        "chunk_characters": 4000,
        "source_sha256": sha256(text.encode()).hexdigest(),
        "output_ids": [f"public:1:model-commentary:{sha256(call.encode()).hexdigest()[:32]}:0"],
    }
    event = SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=0,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        payload={
            "model_call_id": call,
            "assistant_message": text,
            "response_stage": "tool_loop",
            "attempt_number": 1,
            "public_commentary": plan,
        },
    )
    projection = AgUiProjector().project(
        (event,),
        AgUiRunIdentity(session_id=session_id, thread_id="task-1", run_id="run-1"),
    )
    response = next(
        item for item in projection.events if getattr(item, "name", None) == "zebra.model_response"
    )
    assert response.value["public_commentary"] == plan
    assert response.value["attempt_number"] == 1
    assert response.value["assistant_message"] == text
    assert response.value["message_id"] == f"message:{call}"
