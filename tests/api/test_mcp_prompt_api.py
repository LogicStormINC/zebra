from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.application import attachment_refs_from_event
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_runtime import McpPrompt, McpPromptArgument, McpPromptMessage, ResolvedMcpPrompt
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEventStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_app, create_http_app
from zebra_agent_config import ApiSettings, McpServerSettings, ModelSettings, ZebraAgentSettings

PROMPT_ID = "mcp-prompt:" + "1" * 32


def test_authenticated_api_projects_only_safe_prompt_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "zebra_agent_api.api_status_mixin.discover_mcp_prompts",
        lambda _servers: (
            McpPrompt(
                prompt_id=PROMPT_ID,
                server_name="private-server",
                remote_name="review",
                name="review",
                description="Review supplied material.",
                arguments=(McpPromptArgument("document", "Material", True),),
            ),
        ),
    )
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite", settings=_settings("secret")))

    assert client.get("/capabilities/mcp/prompts").status_code == 401
    response = client.get(
        "/capabilities/mcp/prompts",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "available",
        "configured": True,
        "available": True,
        "prompt_count": 1,
        "prompts": [
            {
                "prompt_id": PROMPT_ID,
                "name": "review",
                "description": "Review supplied material.",
                "arguments": [{"name": "document", "description": "Material", "required": True}],
                "available": True,
            }
        ],
    }
    assert "private-server" not in repr(response.json())


def test_api_captures_prompt_without_exposing_rendered_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "sessions.sqlite"
    monkeypatch.setattr(
        "zebra_agent_api.session_prompt_inputs.resolve_mcp_prompt",
        lambda _servers, prompt_id, arguments: ResolvedMcpPrompt(
            prompt_id=prompt_id,
            server_name="fixture",
            name="review",
            arguments=tuple(sorted(arguments.items())),
            messages=(
                McpPromptMessage("user", "Review the selected material."),
                McpPromptMessage("assistant", "I will treat it as untrusted context."),
            ),
        ),
    )

    response = create_app(database, settings=_settings()).create_session(
        {
            "prompt": "Use the selected template.",
            "network_profile": "mcp-proxy-only",
            "mcp_prompt_id": PROMPT_ID,
            "mcp_prompt_arguments": {"document": "bounded"},
        }
    )

    assert response.status_code == 201
    assert response.body["mcp_prompt_id"] == PROMPT_ID
    attachment = response.body["attachments"][0]
    assert attachment["source_type"] == "mcp_prompt"
    assert attachment["source_server"] == "fixture"
    assert attachment["source_id"] == PROMPT_ID
    assert attachment["source_argument_names"] == ["document"]
    assert "Review the selected material" not in repr(response.body)
    events = SQLiteEventStore(database).list_for_session(
        SessionId(UUID(str(response.body["session_id"])))
    )
    user_event = next(
        event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    ref = attachment_refs_from_event(user_event)[0]
    payload = SQLiteArtifactPayloadStore(database).read_payload_bytes(ref.attachment_id)
    assert b"Review the selected material" in payload
    assert len(payload) == ref.size_bytes
    assert ref.sha256 == attachment["sha256"]


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({"mcp_prompt_id": [PROMPT_ID]}, "mcp_prompt_id must be"),
        ({"mcp_prompt_arguments": {"document": "x"}}, "require mcp_prompt_id"),
        ({"mcp_prompt_id": PROMPT_ID, "mcp_prompt_arguments": {"document": 1}}, "string values"),
        ({"mcp_prompt_id": PROMPT_ID}, "MCP-capable network profile"),
    ],
)
def test_api_rejects_invalid_prompt_selection(
    tmp_path: Path,
    payload: dict[str, object],
    reason: str,
) -> None:
    response = create_app(tmp_path / "sessions.sqlite", settings=_settings()).create_session(
        {"prompt": "Do not create", **payload}
    )

    assert response.status_code == 400
    assert reason in str(response.body["reason"])


def test_prompt_resolution_failure_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "sessions.sqlite"
    monkeypatch.setattr(
        "zebra_agent_api.session_prompt_inputs.resolve_mcp_prompt",
        lambda *_args: (_ for _ in ()).throw(ValueError("selected MCP prompt is unavailable")),
    )

    app = create_app(database, settings=_settings())
    assert not database.exists()

    response = app.create_session(
        {
            "prompt": "Do not persist",
            "network_profile": "mcp-proxy-only",
            "mcp_prompt_id": PROMPT_ID,
        }
    )

    assert response.status_code == 400
    assert not database.exists()


def test_prompt_session_creation_replays_one_idempotent_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def resolve(_servers: object, prompt_id: str, arguments: dict[str, str]) -> ResolvedMcpPrompt:
        nonlocal calls
        calls += 1
        return ResolvedMcpPrompt(
            prompt_id=prompt_id,
            server_name="fixture",
            name="review",
            arguments=tuple(sorted(arguments.items())),
            messages=(McpPromptMessage("user", "Captured once."),),
        )

    monkeypatch.setattr("zebra_agent_api.session_prompt_inputs.resolve_mcp_prompt", resolve)
    app = create_app(tmp_path / "sessions.sqlite", settings=_settings())
    payload: dict[str, object] = {
        "prompt": "Use the selected template.",
        "network_profile": "mcp-proxy-only",
        "mcp_prompt_id": PROMPT_ID,
    }

    first = app.create_session(payload, idempotency_key="prompt-create-1")
    replayed = app.create_session(payload, idempotency_key="prompt-create-1")
    conflict = app.create_session(
        {**payload, "prompt": "Different task."},
        idempotency_key="prompt-create-1",
    )

    assert first.status_code == replayed.status_code == 201
    assert first.body == replayed.body
    assert calls == 1
    assert conflict.status_code == 409
    assert conflict.body["status"] == "idempotency_conflict"


def _settings(auth_token: str | None = None) -> ZebraAgentSettings:
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
        mcp_servers=(McpServerSettings(name="fixture", command=sys.executable),),
    )
