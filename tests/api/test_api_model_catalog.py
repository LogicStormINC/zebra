import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import zebra_agent_api.app as api_app_module
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_storage import SQLiteEventStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_config import load_settings


def _catalog_json(*, default_id: str = "qwen-native", deepseek_available: bool = False) -> str:
    return json.dumps(
        {
            "default_id": default_id,
            "models": [
                {
                    "id": "qwen-native",
                    "label": "Qwen native media",
                    "available": True,
                    "settings": {
                        "provider": "qwen",
                        "api_key_env": "DASHSCOPE_API_KEY",
                        "base_url": "https://dashscope.example.test/v1",
                        "model": "qwen3.7-flash",
                        "profile_id": "qwen-flash-alias-native-v1",
                    },
                },
                {
                    "id": "deepseek-text",
                    "label": "DeepSeek text with MCP",
                    "available": deepseek_available,
                    "settings": {
                        "provider": "deepseek",
                        "api_key_env": "DEEPSEEK_API_KEY",
                        "base_url": "https://deepseek.example.test/v1",
                        "model": "deepseek-v4-flash",
                    },
                },
            ],
        }
    )


def test_health_projects_native_image_capability_from_catalog_default(tmp_path: Path) -> None:
    database = tmp_path / "health-qwen.sqlite"
    settings = load_settings(
        {
            "ZEBRA_DATABASE_URL": str(database),
            "ZEBRA_MODEL_CATALOG_JSON": _catalog_json(),
        }
    )

    runtime = create_app(database, settings=settings).health().body["runtime"]

    assert runtime["native_image_understanding"] is True


def test_health_projects_text_capability_from_catalog_default(tmp_path: Path) -> None:
    database = tmp_path / "health-deepseek.sqlite"
    settings = load_settings(
        {
            "ZEBRA_DATABASE_URL": str(database),
            "ZEBRA_MODEL_CATALOG_JSON": _catalog_json(
                default_id="deepseek-text",
                deepseek_available=True,
            ),
        }
    )

    runtime = create_app(database, settings=settings).health().body["runtime"]

    assert runtime["native_image_understanding"] is False


def _adapter(database: Path) -> RouteAdapter:
    settings = load_settings(
        {
            "ZEBRA_DATABASE_URL": str(database),
            "ZEBRA_MODEL_CATALOG_JSON": _catalog_json(),
        }
    )
    return RouteAdapter(create_app(database, settings=settings))


def test_model_capabilities_expose_only_safe_catalog_fields(tmp_path: Path) -> None:
    response = _adapter(tmp_path / "models.sqlite").handle(
        RouteRequest("GET", "/capabilities/models")
    )

    assert response.status_code == 200
    assert response.body == {
        "schema_version": "zebra.model-catalog.v1",
        "default_id": "qwen-native",
        "models": [
            {"id": "qwen-native", "label": "Qwen native media", "available": True},
            {"id": "deepseek-text", "label": "DeepSeek text with MCP", "available": False},
        ],
    }
    serialized = json.dumps(response.body)
    assert "base_url" not in serialized
    assert "api_key_env" not in serialized
    assert "DASHSCOPE_API_KEY" not in serialized
    assert "schema" not in response.body


def test_task_model_selection_is_persisted_in_task_prepared_event(tmp_path: Path) -> None:
    database = tmp_path / "models.sqlite"
    response = _adapter(database).handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "prompt": "Inspect the repository",
                "workspace": str(tmp_path),
                "model": "qwen-native",
            },
        )
    )

    assert response.status_code == 201
    assert response.body["model"] == "qwen-native"
    events = SQLiteEventStore(database).list_for_session(
        SessionId(UUID(str(response.body["task_id"])))
    )
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["model_id"] == "qwen-native"


def test_execute_task_builds_gateway_from_selected_catalog_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: list[object] = []

    def fake_build_model_gateway(settings):
        captured.append(settings.model)
        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Selected model completed.",
                            created_at=datetime.now(UTC),
                        )
                    )
                ),
            )
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)
    database = tmp_path / "models.sqlite"
    settings = load_settings(
        {
            "ZEBRA_DATABASE_URL": str(database),
            "ZEBRA_MODEL_CATALOG_JSON": _catalog_json(),
        }
    )
    response = create_app(database, settings=settings).create_session(
        {
            "prompt": "Inspect",
            "workspace": str(tmp_path),
            "model": "qwen-native",
            "execute": True,
        }
    )

    assert response.status_code == 201
    assert captured[0].provider == "qwen"
    assert captured[0].model == "qwen3.7-flash"
    assert captured[0].profile_id == "qwen-flash-alias-native-v1"


def test_unknown_and_unavailable_task_models_fail_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "models.sqlite")

    unknown = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={"prompt": "Inspect", "workspace": str(tmp_path), "model": "missing"},
        )
    )
    unavailable = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "prompt": "Inspect",
                "workspace": str(tmp_path),
                "model": "deepseek-text",
            },
        )
    )

    assert unknown.status_code == 400
    assert "unknown model catalog id" in str(unknown.body["reason"])
    assert unavailable.status_code == 400
    assert "unavailable" in str(unavailable.body["reason"])


def test_task_idempotency_rejects_same_key_with_different_model(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "models.sqlite")
    first = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "prompt": "Inspect",
                "workspace": str(tmp_path),
                "model": "qwen-native",
            },
            headers={"Idempotency-Key": "model-choice-1"},
        )
    )
    conflict = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "prompt": "Inspect",
                "workspace": str(tmp_path),
                "model": "deepseek-text",
            },
            headers={"Idempotency-Key": "model-choice-1"},
        )
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.body["status"] == "idempotency_conflict"


def test_create_task_keeps_unknown_fields_strict_with_model_selector(tmp_path: Path) -> None:
    response = _adapter(tmp_path / "models.sqlite").handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "prompt": "Inspect",
                "workspace": str(tmp_path),
                "model": "qwen-native",
                "not_a_create_session_field": True,
            },
        )
    )

    assert response.status_code == 400
    assert response.body["reason"] == (
        "unknown create-session fields: not_a_create_session_field"
    )
