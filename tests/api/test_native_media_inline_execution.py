from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import zebra_agent_api.app as api_app_module
import zebra_agent_worker.execution as worker_execution_module
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_integrations import OpenAICompatibleModelGateway
from agent_integrations.openai_model_profiles import resolve_model_profile
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEventStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings

PNG = b"\x89PNG\r\n\x1a\nZEBRA-NATIVE-INLINE"


def test_inline_native_media_uses_one_user_event_id_and_no_legacy_image_tool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request_bodies: list[dict[str, object]] = []
    harness_calls: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        request_bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text=(
                'data: {"model":"qwen3.7-flash-2026-07-15","choices":'
                '[{"delta":{"content":"Reviewed."}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://qwen.example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        media_capabilities=resolve_model_profile(
            "qwen-flash-native-v1",
            provider="qwen",
            model="qwen3.7-flash-2026-07-15",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    original_run_local_harness = api_app_module.run_local_harness

    def capture_harness(**kwargs):
        harness_calls.append(kwargs)
        return original_run_local_harness(**kwargs)

    monkeypatch.setattr(api_app_module, "build_model_gateway", lambda _settings: gateway)
    monkeypatch.setattr(api_app_module, "run_local_harness", capture_harness)
    database_path = tmp_path / "tasks.sqlite"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "title": "Native image review",
            "prompt": "Review this image.",
            "workspace": str(tmp_path),
            "execute": True,
            "attachments": [
                {
                    "file_name": "review.png",
                    "media_type": "image/png",
                    "content_base64": base64.b64encode(PNG).decode("ascii"),
                }
            ],
        }
    )

    assert response.status_code == 201
    assert len(request_bodies) == 1
    assert len(harness_calls) == 1
    [media] = harness_calls[0]["media_inputs"]
    initial_user_event_id = harness_calls[0]["initial_user_event_id"]
    assert media.source_message_id == initial_user_event_id
    assert harness_calls[0]["disabled_mcp_tools"] == ("mcp.minimax.understand_image",)

    body = request_bodies[0]
    assert body["enable_thinking"] is False
    messages = body["messages"]
    assert isinstance(messages, list)
    user_message = next(message for message in messages if message["role"] == "user")
    parts = user_message["content"]
    assert parts[0] == {"type": "text", "text": "Review this image."}
    assert parts[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
    )

    session_id = SessionId(response.body["session_id"])
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    user_event = next(
        event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    assert user_event.event_id == initial_user_event_id
    [attachment] = user_event.payload["attachments"]
    assert attachment["message_event_id"] == str(initial_user_event_id)
    assert SQLiteArtifactPayloadStore(database_path).read_payload_bytes(media.artifact_id) == PNG
    assert base64.b64encode(PNG).decode("ascii") not in json.dumps(
        [event.payload for event in events], sort_keys=True
    )


def test_worker_replays_native_media_after_terminal_follow_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request_bodies: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        request_bodies.append(body)
        if body["stream"]:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                text=(
                    'data: {"model":"qwen3.7-flash-2026-07-15","choices":'
                    '[{"delta":{"content":"Reviewed."}}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        return httpx.Response(
            200,
            json={
                "model": "qwen3.7-flash-2026-07-15",
                "choices": [{"message": {"role": "assistant", "content": "Image review"}}],
            },
        )

    def build_gateway(_settings: ZebraAgentSettings) -> OpenAICompatibleModelGateway:
        return OpenAICompatibleModelGateway(
            provider_name="qwen",
            base_url="https://qwen.example.test/compatible-mode/v1",
            api_key="test-only-secret",
            model_name="qwen3.7-flash-2026-07-15",
            media_capabilities=resolve_model_profile(
                "qwen-flash-native-v1",
                provider="qwen",
                model="qwen3.7-flash-2026-07-15",
            ),
            client=httpx.Client(transport=httpx.MockTransport(handle)),
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", build_gateway)
    database_path = tmp_path / "tasks.sqlite"
    adapter = RouteAdapter(create_app(database_path, settings=_settings(database_path)))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Queued native review",
                "prompt": "Review this image.",
                "attachments": [
                    {
                        "file_name": "review.png",
                        "media_type": "image/png",
                        "content_base64": base64.b64encode(PNG).decode("ascii"),
                    }
                ],
            },
        )
    )
    task_id = created.body["task_id"]

    first = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/resume", body={}))
    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={"content": "Continue the same image review."},
        )
    )
    follow_up = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/resume", body={}))

    assert first.status_code == 200
    assert appended.status_code == 201
    assert appended.body["rolled_over"] is True
    assert follow_up.status_code == 200
    streaming_requests = [body for body in request_bodies if body["stream"] is True]
    assert len(streaming_requests) == 2
    for body in streaming_requests:
        assert body["enable_thinking"] is False
        messages = body["messages"]
        assert isinstance(messages, list)
        user_message = next(message for message in messages if message["role"] == "user")
        parts = user_message["content"]
        assert parts[1]["image_url"]["url"] == (
            "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
        )


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="qwen",
            api_key_env="DASHSCOPE_API_KEY",
            base_url="https://qwen.example.test/compatible-mode/v1",
            model="qwen3.7-flash-2026-07-15",
            profile_id="qwen-flash-native-v1",
        ),
    )
