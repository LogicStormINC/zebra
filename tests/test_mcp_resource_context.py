from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.application import attachment_refs_from_event
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_runtime import discover_mcp_resources
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEventStore
from zebra_agent_api import create_app
from zebra_agent_cli.cli import execute
from zebra_agent_config import (
    ApiSettings,
    McpServerSettings,
    ModelSettings,
    ZebraAgentSettings,
)


def test_api_captures_safe_resource_snapshot_atomically(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    marker = tmp_path / "resource-read"
    settings = _settings(database, marker=marker)
    resource_id = discover_mcp_resources(settings.mcp_servers)[0].resource_id
    app = create_app(database, settings=settings)

    response = app.create_session(
        {
            "prompt": "Use the selected reference.",
            "workspace": str(tmp_path),
            "network_profile": "mcp-proxy-only",
            "mcp_resource_ids": [resource_id],
        }
    )

    assert response.status_code == 201
    assert response.body["mcp_resource_ids"] == [resource_id]
    attachment = response.body["attachments"][0]
    assert attachment["source_type"] == "mcp_resource"
    assert attachment["source_server"] == "fixture"
    assert attachment["source_id"] == resource_id
    assert "resource://" not in repr(response.body)
    assert marker.read_text(encoding="utf-8") == "resource-read"
    events = SQLiteEventStore(database).list_for_session(
        SessionId(UUID(str(response.body["session_id"])))
    )
    user_event = next(
        event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    refs = attachment_refs_from_event(user_event)
    assert refs[0].source_id == resource_id
    assert "MCP_RESOURCE_CONTEXT_136" not in repr(user_event.payload)
    assert "resource://" not in repr(user_event.payload)
    assert SQLiteArtifactPayloadStore(database).read_payload_bytes(
        refs[0].attachment_id
    ) == b"MCP_RESOURCE_CONTEXT_136"

    failed = app.create_session(
        {
            "prompt": "Do not create this task.",
            "network_profile": "mcp-proxy-only",
            "mcp_resource_ids": ["mcp-resource:fixture:removed"],
        }
    )
    assert failed.status_code == 400
    assert app.list_sessions({}).body["count"] == 1


def test_worker_recovers_snapshot_without_rereading_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "sessions.sqlite"
    marker = tmp_path / "resource-read"
    settings = _settings(database, marker=marker, mode="resources-only")
    resource_id = discover_mcp_resources(settings.mcp_servers)[0].resource_id
    app = create_app(database, settings=settings)
    created = app.create_session(
        {
            "prompt": "Answer from the captured reference.",
            "workspace": str(tmp_path),
            "network_profile": "mcp-proxy-only",
            "mcp_resource_ids": [resource_id],
        }
    )
    marker.write_text("after-task-creation", encoding="utf-8")
    requests: list[tuple[SessionMessage, ...]] = []

    class RecordingGateway:
        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            assert all("resource" not in tool.name.lower() for tool in tools)
            requests.append(tuple(messages))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Recovered resource context.",
                    created_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RecordingGateway(),
    )
    resumed = app.resume_session(created.body["session_id"], {"worker_id": "resource-worker"})

    assert resumed.status_code == 200
    assert marker.read_text(encoding="utf-8") == "after-task-creation"
    assert "[mcp_resource] brief.txt" in requests[0][0].content
    assert "Untrusted MCP Resource material" in requests[0][0].content
    assert "MCP_RESOURCE_CONTEXT_136" in requests[0][0].content
    assert requests[0][-1].content == "Answer from the captured reference."


def test_cli_queued_run_persists_selected_resource(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    settings = _settings(database)
    resource_id = discover_mcp_resources(settings.mcp_servers)[0].resource_id

    result = execute(
        [
            "run",
            "Use selected reference",
            "--network-profile",
            "mcp-proxy-only",
            "--mcp-resource",
            resource_id,
        ],
        settings=settings,
    )

    assert result.payload["mcp_resource_ids"] == [resource_id]
    assert result.payload["attachments"][0]["source_id"] == resource_id
    assert "resource://" not in repr(result.payload)


def _settings(
    database: Path,
    *,
    marker: Path | None = None,
    mode: str = "resource",
) -> ZebraAgentSettings:
    script = Path(__file__).parent / "fixtures" / "mcp_stdio_server.py"
    args = [str(script), mode]
    if marker is not None:
        args.append(str(marker))
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
        mcp_servers=(
            McpServerSettings(
                name="fixture",
                command=sys.executable,
                args=tuple(args),
            ),
        ),
    )
