from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import zebra_agent_api.api_session_message_append_mixin as append_mixin_module
import zebra_agent_api.app as api_app_module
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_storage import SQLiteEventStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings

PNG = b"\x89PNG\r\n\x1a\nZEBRA-DURABILITY"


def test_queued_create_removes_images_when_event_write_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    captured = _capture_staged_images(monkeypatch)
    monkeypatch.setattr(
        api_app_module.SQLiteEventStore,
        "append",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("event write failed")),
    )
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))

    with pytest.raises(RuntimeError, match="event write failed"):
        adapter.handle(RouteRequest("POST", "/tasks", body=_task_payload()))

    assert captured[0].images[0].path.exists() is False


@pytest.mark.parametrize("execute", [False, True])
def test_create_retains_durable_image_when_projection_save_fails(
    tmp_path: Path,
    monkeypatch,
    execute: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    captured = _capture_staged_images(monkeypatch)
    monkeypatch.setattr(api_app_module, "build_model_gateway", lambda _settings: _Gateway())
    monkeypatch.setattr(
        api_app_module.SQLiteProjectionStore,
        "save_session",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("projection write failed")),
    )
    database = tmp_path / "tasks.sqlite"
    adapter = RouteAdapter(create_app(database, settings=_settings(database)))

    with pytest.raises(RuntimeError, match="projection write failed"):
        adapter.handle(RouteRequest("POST", "/tasks", body=_task_payload(execute=execute)))

    staged = captured[0]
    assert staged.images[0].path.exists()
    _assert_durable_image_event(
        database,
        staged.workspace_root.name,
        staged.images[0].workspace_path,
    )


def test_inline_create_removes_images_when_harness_raises_unexpectedly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    captured = _capture_staged_images(monkeypatch)
    monkeypatch.setattr(api_app_module, "build_model_gateway", lambda _settings: _Gateway())
    monkeypatch.setattr(
        api_app_module,
        "run_local_harness",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("harness crashed")),
    )
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))

    with pytest.raises(RuntimeError, match="harness crashed"):
        adapter.handle(RouteRequest("POST", "/tasks", body=_task_payload(execute=True)))

    assert captured[0].images[0].path.exists() is False


def test_append_retains_durable_image_when_projection_save_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "tasks.sqlite"
    adapter = RouteAdapter(create_app(database, settings=_settings(database)))
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"title": "Review", "prompt": "Start."})
    )
    captured = _capture_staged_images(monkeypatch, module=append_mixin_module)
    monkeypatch.setattr(
        api_app_module.SQLiteProjectionStore,
        "save_session",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("projection write failed")),
    )

    with pytest.raises(RuntimeError, match="projection write failed"):
        adapter.handle(
            RouteRequest(
                "POST",
                f"/tasks/{created.body['task_id']}/messages",
                body={"content": "Review this.", "attachments": [_attachment()]},
            )
        )

    staged = captured[0]
    assert staged.images[0].path.exists()
    _assert_durable_image_event(database, created.body["task_id"], staged.images[0].workspace_path)


def _capture_staged_images(monkeypatch, *, module=api_app_module) -> list[object]:
    captured: list[object] = []
    original = module.stage_task_images

    def capture(*args, **kwargs):
        staged = original(*args, **kwargs)
        captured.append(staged)
        return staged

    monkeypatch.setattr(module, "stage_task_images", capture)
    return captured


def _assert_durable_image_event(database: Path, session_id: str, workspace_path: str) -> None:
    events = SQLiteEventStore(database).list_for_session(SessionId(UUID(session_id)))
    assert any(
        event.event_type is EventType.USER_MESSAGE_RECEIVED
        and any(
            attachment.get("workspace_path") == workspace_path
            for attachment in event.payload.get("attachments", [])
        )
        for event in events
    )


def _task_payload(*, execute: bool = False) -> dict[str, object]:
    return {
        "title": "Review",
        "prompt": "Review this image.",
        "execute": execute,
        "attachments": [_attachment()],
    }


def _attachment() -> dict[str, str]:
    return {
        "file_name": "review.png",
        "media_type": "image/png",
        "content_base64": base64.b64encode(PNG).decode("ascii"),
    }


def _settings(database: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


class _Gateway:
    def complete(
        self,
        _messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        del tools
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="Done.",
                created_at=datetime(2026, 7, 26, tzinfo=UTC),
            )
        )
