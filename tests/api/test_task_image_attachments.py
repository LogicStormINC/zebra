from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import zebra_agent_api.app as api_app_module
import zebra_agent_worker.execution as worker_execution_module
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.tools import ToolCall
from agent_storage import SQLiteEventStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.session_attachment_inputs import MAX_IMAGE_BYTES, parse_attachment_inputs
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings

PNG = b"\x89PNG\r\n\x1a\nZEBRA-TASK-IMAGE"
JPEG = b"\xff\xd8\xffZEBRA-TASK-IMAGE"


def test_task_png_attachment_is_staged_under_a_stable_server_owned_task_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "tasks.sqlite"
    finos_workspace = tmp_path / "finos-private"
    finos_workspace.mkdir()
    adapter = RouteAdapter(create_app(database, settings=_settings(database)))

    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Image review",
                "prompt": "Review this screenshot.",
                "workspace": str(finos_workspace),
                "attachments": [
                    {
                        "file_name": "broker.png",
                        "media_type": "image/png",
                        "content_base64": base64.b64encode(PNG).decode("ascii"),
                    }
                ],
            },
        )
    )

    assert created.status_code == 201
    [attachment] = created.body["attachments"]
    assert attachment["media_type"] == "image/png"
    assert attachment["storage_kind"] == "task_workspace"
    relative_path = attachment["workspace_path"]
    assert relative_path.startswith("images/")
    assert Path(relative_path).is_absolute() is False
    assert (
        tmp_path / ".zebra-agent" / "task-workspaces" / created.body["task_id"] / relative_path
    ).read_bytes() == PNG
    assert "workspace" not in created.body

    events = SQLiteEventStore(database).list_for_session(created.body["task_id"])
    serialized = json.dumps([event.payload for event in events], sort_keys=True)
    assert relative_path in serialized
    assert str(finos_workspace) not in serialized
    streamed = adapter.handle(RouteRequest("GET", f"/tasks/{created.body['task_id']}/stream"))
    assert str(finos_workspace) not in json.dumps(streamed.body, sort_keys=True)


def test_task_follow_up_stages_a_second_image_in_the_same_task_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Image review",
                "prompt": "Review the first screenshot.",
                "attachments": [_attachment("first.png", "image/png", PNG)],
            },
        )
    )
    task_id = created.body["task_id"]
    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "Now compare the second screenshot.",
                "attachments": [_attachment("second.jpg", "image/jpeg", JPEG)],
            },
        )
    )

    assert appended.status_code == 201
    first = created.body["attachments"][0]
    second = appended.body["attachments"][0]
    root = tmp_path / ".zebra-agent" / "task-workspaces" / task_id
    assert (root / first["workspace_path"]).read_bytes() == PNG
    assert (root / second["workspace_path"]).read_bytes() == JPEG
    assert first["workspace_path"] != second["workspace_path"]


def test_task_images_are_isolated_between_tasks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))
    first = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "First image review",
                "prompt": "Review this screenshot.",
                "attachments": [_attachment("same-name.png", "image/png", PNG)],
            },
        )
    )
    second = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Second image review",
                "prompt": "Review this screenshot.",
                "attachments": [_attachment("same-name.png", "image/png", PNG)],
            },
        )
    )

    first_id = first.body["task_id"]
    second_id = second.body["task_id"]
    first_path = first.body["attachments"][0]["workspace_path"]
    second_path = second.body["attachments"][0]["workspace_path"]
    first_root = tmp_path / ".zebra-agent" / "task-workspaces" / first_id
    second_root = tmp_path / ".zebra-agent" / "task-workspaces" / second_id

    assert first.status_code == second.status_code == 201
    assert first_root != second_root
    assert (first_root / first_path).read_bytes() == PNG
    assert (second_root / second_path).read_bytes() == PNG
    assert not (first_root / second_path).exists()
    assert not (second_root / first_path).exists()


def test_task_image_staging_rejects_a_symlinked_images_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Image review",
                "prompt": "Review this screenshot.",
                "attachments": [_attachment("first.png", "image/png", PNG)],
            },
        )
    )
    root = tmp_path / ".zebra-agent" / "task-workspaces" / created.body["task_id"]
    image_path = root / created.body["attachments"][0]["workspace_path"]
    image_path.unlink()
    (root / "images").rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "images").symlink_to(outside, target_is_directory=True)

    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{created.body['task_id']}/messages",
            body={
                "content": "Try an unsafe replacement.",
                "attachments": [_attachment("second.png", "image/png", PNG)],
            },
        )
    )

    assert appended.status_code == 400
    assert "must not be a symlink" in appended.body["reason"]
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("file_name", "media_type", "payload", "reason"),
    [
        ("wrong.jpg", "image/png", PNG, "inconsistent extension"),
        ("wrong.png", "image/png", b"not-an-image", "magic bytes are invalid"),
    ],
)
def test_image_attachments_require_matching_extension_and_magic(
    file_name: str,
    media_type: str,
    payload: bytes,
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_attachment_inputs([_attachment(file_name, media_type, payload)])


def test_image_attachment_enforces_the_five_mebibyte_limit() -> None:
    with pytest.raises(ValueError, match="5242880-byte limit"):
        parse_attachment_inputs(
            [_attachment("large.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_BYTES)]
        )


def test_inline_task_uses_its_image_root_for_the_minimax_overlay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    roots: list[Path] = []
    original_overlay = api_app_module.with_task_workspace_root
    monkeypatch.setattr(api_app_module, "build_model_gateway", lambda _settings: _Gateway())
    monkeypatch.setattr(
        api_app_module,
        "with_task_workspace_root",
        lambda servers, root: (roots.append(root), original_overlay(servers, root))[1],
    )
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))

    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Inline image review",
                "prompt": "Review this screenshot.",
                "execute": True,
                "attachments": [_attachment("inline.png", "image/png", PNG)],
            },
        )
    )

    assert created.status_code == 201
    assert roots == [tmp_path / ".zebra-agent" / "task-workspaces" / created.body["task_id"]]


def test_worker_uses_the_same_task_image_root_after_queue_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    roots: list[Path] = []
    original_overlay = worker_execution_module.with_task_workspace_root
    monkeypatch.setattr(
        worker_execution_module, "build_model_gateway", lambda _settings: _Gateway()
    )
    monkeypatch.setattr(
        worker_execution_module,
        "with_task_workspace_root",
        lambda servers, root: (roots.append(root), original_overlay(servers, root))[1],
    )
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Queued image review",
                "prompt": "Review this screenshot.",
                "attachments": [_attachment("queued.png", "image/png", PNG)],
            },
        )
    )

    resumed = adapter.handle(
        RouteRequest("POST", f"/tasks/{created.body['task_id']}/resume", body={})
    )

    assert resumed.status_code == 200
    assert roots == [tmp_path / ".zebra-agent" / "task-workspaces" / created.body["task_id"]]


def test_task_image_context_survives_a_terminal_follow_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    gateway = _Gateway()
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", lambda _settings: gateway)
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Queued image review",
                "prompt": "Review this screenshot.",
                "attachments": [_attachment("queued.png", "image/png", PNG)],
            },
        )
    )
    task_id = created.body["task_id"]
    image_path = created.body["attachments"][0]["workspace_path"]

    assert (
        adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/resume", body={})).status_code == 200
    )
    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={"content": "Continue the review with the same screenshot."},
        )
    )
    resumed = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/resume", body={}))

    assert appended.status_code == 201
    assert appended.body["rolled_over"] is True
    assert resumed.status_code == 200
    assert any(image_path in message.content for message in gateway.requests[-2])


def test_task_image_context_survives_a_clarification_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    clarification = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={"question": "Which part of the image should I inspect?"},
        created_at=datetime(2026, 7, 26, tzinfo=UTC),
    )
    initial_gateway = _Gateway(tool_call=clarification)
    final_gateway = _Gateway()
    gateways = iter((initial_gateway, final_gateway))
    monkeypatch.setattr(
        worker_execution_module, "build_model_gateway", lambda _settings: next(gateways)
    )
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite", settings=_settings(tmp_path)))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Clarify image review",
                "prompt": "Review this screenshot.",
                "attachments": [_attachment("clarify.png", "image/png", PNG)],
            },
        )
    )
    task_id = created.body["task_id"]
    image_path = created.body["attachments"][0]["workspace_path"]

    waiting = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/resume", body={}))
    response = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "Inspect the chart trend.",
                "clarification_id": str(clarification.tool_call_id),
            },
        )
    )
    completed = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/resume", body={}))

    assert waiting.body["status"] == "waiting_input"
    assert response.status_code == 201
    assert response.body["clarification_resolved"] is True
    assert completed.body["status"] == "completed"
    assert any(image_path in message.content for message in final_gateway.requests[0])


def _attachment(file_name: str, media_type: str, payload: bytes) -> dict[str, str]:
    return {
        "file_name": file_name,
        "media_type": media_type,
        "content_base64": base64.b64encode(payload).decode("ascii"),
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
    def __init__(self, tool_call: ToolCall | None = None) -> None:
        self.requests: list[list[SessionMessage]] = []
        self._tool_call = tool_call

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        del tools
        self.requests.append(messages)
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="Image task complete.",
                created_at=datetime(2026, 7, 26, tzinfo=UTC),
            ),
            tool_calls=(self._tool_call,) if self._tool_call is not None else (),
        )
