from datetime import UTC, datetime
from pathlib import Path

import zebra_agent_worker.execution as worker_execution_module
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def _finish_first_turn(database_path: Path, session_id: str) -> None:
    """Close bootstrap Turn 0 so a follow-up message can be admitted."""
    from uuid import UUID

    from agent_core.application import current_turn
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import SessionId
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore as _Store
    from agent_storage import SQLiteProjectionStore as _Proj

    key = SessionId(UUID(str(session_id)))
    event_store = _Store(database_path)
    events = event_store.list_for_session(key)
    session = events[0].session_id
    open_turn = current_turn(events)
    turn_id = (
        open_turn.turn_id if open_turn else str(derive_turn_id(session, 0))
    )
    turn_index = open_turn.turn_index if open_turn else 0
    base = events[-1].sequence
    event_store.append(
        SessionEvent.create(
            session_id=session,
            sequence=base + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session,
            sequence=base + 2,
            event_type=EventType.TURN_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "turn_id": turn_id,
                "turn_index": turn_index,
                "closes_segment": False,
            },
        )
    )
    _Proj(database_path).save_session(
        rebuild_session(event_store.list_for_session(key))
    )



def _settings(auth_token: str | None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )

def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 6, 22, 13, 25, tzinfo=UTC)

def _seed_ready_session(database_path: Path, *, workspace_root: Path) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="HTTP queued session",
            user_input="Summarize the workspace",
            workspace_root=workspace_root,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return str(bootstrap.session.session_id)

def _fake_resume_gateway(_settings: ZebraAgentSettings) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="HTTP resume complete.",
                        created_at=datetime(2026, 6, 22, 13, 25, tzinfo=UTC),
                    )
                )
            ),
        )
    )

def _counting_gateway(monkeypatch, counter: dict[str, int], *replies: str, gateways=None):
    def factory(_settings: ZebraAgentSettings) -> ScriptedModelGateway:
        counter["calls"] += 1
        gateway = ScriptedModelGateway(
            responses=tuple(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content=reply,
                            created_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
                        )
                    )
                )
                for reply in replies
            )
        )
        if gateways is not None:
            gateways.append(gateway)
        return gateway

    monkeypatch.setattr(worker_execution_module, "build_model_gateway", factory)


def _create_conversation_task(client: TestClient, *, workspace_root: Path) -> str:
    response = client.post(
        "/tasks",
        json={
            "prompt": "Remember the codeword is granite.",
            "title": "Conversation acceptance",
            "interaction_mode": "conversation",
            "workspace": str(workspace_root),
        },
    )
    assert response.status_code == 201
    return str(response.json()["task_id"])


def _run_turn(client: TestClient, task_id: str) -> dict[str, object]:
    response = client.post(f"/tasks/{task_id}/resume", json={})
    assert response.status_code == 200, response.text
    return response.json()
