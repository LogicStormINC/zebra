from pathlib import Path

import zebra_agent_api.app as api_app_module
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.tools import ToolCall
from agent_storage import SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_api_health_returns_service_status(tmp_path: Path) -> None:
    app = create_app(tmp_path / "sessions.sqlite")

    response = app.health()

    assert response.status_code == 200
    assert response.body == {
        "service": "zebra-agent-api",
        "status": "ok",
    }


def test_api_create_app_uses_settings_database_by_default(tmp_path: Path) -> None:
    database_path = tmp_path / "configured.sqlite"
    app = create_app(settings=_settings(database_path))

    assert app.database_path == database_path


def test_api_create_app_database_path_overrides_settings(tmp_path: Path) -> None:
    configured_path = tmp_path / "configured.sqlite"
    explicit_path = tmp_path / "explicit.sqlite"
    app = create_app(explicit_path, settings=_settings(configured_path))

    assert app.database_path == explicit_path


def test_api_get_session_returns_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="API session")
    )

    response = create_app(database_path).get_session(str(session.session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session.session_id),
        "title": "API session",
        "status": SessionStatus.CREATED.value,
        "current_sequence": 0,
    }


def test_api_get_session_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_get_session_stream_returns_persisted_events(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = Session.create(title="API stream")
    projection_store = SQLiteProjectionStore(database_path)
    projection_store.save_session(session)
    from agent_storage import SQLiteEventStore

    event_store = SQLiteEventStore(database_path)
    created = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    prepared = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": session.title,
                "user_input": "stream me",
            },
        )
    )

    response = create_app(database_path).get_session_stream(str(session.session_id))

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert response.body["events"] == [
        {
            "event_id": str(created.event_id),
            "sequence": 0,
            "event_type": EventType.SESSION_CREATED.value,
            "actor": EventActor.USER.value,
            "created_at": created.created_at.isoformat(),
            "payload": {"title": session.title},
        },
        {
            "event_id": str(prepared.event_id),
            "sequence": 1,
            "event_type": EventType.TASK_PREPARED.value,
            "actor": EventActor.HARNESS.value,
            "created_at": prepared.created_at.isoformat(),
            "payload": {
                "title": session.title,
                "user_input": "stream me",
                "workspace_root": None,
                "policy_profile": None,
                "max_attempts": None,
                "max_model_calls": None,
                "max_tool_calls": None,
            },
        },
    ]


def test_api_get_session_stream_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_stream(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_create_session_persists_created_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Inspect the workspace",
            "title": "API create session",
        }
    )

    session = SQLiteProjectionStore(database_path).get_session(
        SessionId(response.body["session_id"])
    )

    assert response.status_code == 201
    assert response.body["executed"] is False
    assert response.body["status"] == SessionStatus.READY.value
    assert session is not None
    assert session.title == "API create session"
    assert session.status is SessionStatus.READY


def test_api_create_session_execute_persists_harness_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse

        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="API execution complete.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Inspect the workspace",
            "title": "API execute session",
            "workspace": str(tmp_path),
            "execute": True,
        }
    )

    session = SQLiteProjectionStore(database_path).get_session(
        SessionId(response.body["session_id"])
    )

    assert response.status_code == 201
    assert response.body["executed"] is True
    assert response.body["status"] == SessionStatus.COMPLETED.value
    assert response.body["assistant_message"] == "API execution complete."
    assert response.body["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "API execution complete.",
            "tools": [],
        }
    ]
    assert session is not None
    assert session.status is SessionStatus.COMPLETED


def test_api_create_session_execute_runs_builtin_tool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    (tmp_path / "README.md").write_text("api readme\n", encoding="utf-8")

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse

        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Reading README.",
                            created_at=_created_at(),
                        ),
                        tool_calls=(
                            ToolCall(
                                tool_call_id=new_tool_call_id(),
                                name="files.read",
                                arguments={"path": "README.md"},
                                created_at=_created_at(),
                            ),
                        ),
                    )
                ),
            )
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Read the README",
            "workspace": str(tmp_path),
            "execute": True,
        }
    )

    assert response.status_code == 201
    assert response.body["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "Reading README.",
            "tools": [
                {
                    "tool_name": "files.read",
                    "status": "executed",
                    "arguments": {"path": "README.md"},
                    "output": "api readme\n",
                    "metadata": {
                        "path": "README.md",
                        "byte_count": 11,
                        "truncated": False,
                    },
                    "policy_decision": "allow",
                    "policy_route": None,
                    "policy_target": None,
                    "policy_network_profile": None,
                    "policy_scope": [],
                }
            ],
        }
    ]


def test_api_create_session_rejects_invalid_request(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {"prompt": "   "}
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "prompt must be a non-blank string",
    }


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


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 6, 22, 13, 20, tzinfo=UTC)
