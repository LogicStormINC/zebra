from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_runtime import discover_mcp_prompts
from zebra_agent_api import create_app
from zebra_agent_config import (
    ApiSettings,
    McpServerSettings,
    ModelSettings,
    ZebraAgentSettings,
)


def test_prompt_launch_survives_server_loss_without_model_prompt_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "sessions.sqlite"
    script = _write_prompt_server(tmp_path)
    marker = tmp_path / "mcp-calls.log"
    settings = _settings(database, script, marker)
    prompt_id = discover_mcp_prompts(settings.mcp_servers)[0].prompt_id
    app = create_app(database, settings=settings)

    inventory = app.get_mcp_prompts()
    created = app.create_session(
        {
            "prompt": "Apply the selected template.",
            "workspace": str(tmp_path),
            "network_profile": "mcp-proxy-only",
            "mcp_prompt_id": prompt_id,
            "mcp_prompt_arguments": {"topic": "durable context"},
        }
    )

    assert inventory.status_code == 200
    assert inventory.body["prompts"][0]["prompt_id"] == prompt_id
    assert "server.py" not in repr(inventory.body)
    assert created.status_code == 201
    calls_before_recovery = marker.read_text(encoding="utf-8")
    script.unlink()
    requests: list[tuple[SessionMessage, ...]] = []
    model_tool_names: list[str] = []

    class RecordingGateway:
        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            model_tool_names.extend(tool.name for tool in tools)
            requests.append(tuple(messages))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Recovered captured prompt context.",
                    created_at=datetime(2026, 7, 16, 20, 0, tzinfo=UTC),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda _settings: RecordingGateway(),
    )
    resumed = app.resume_session(
        str(created.body["session_id"]),
        {"worker_id": "prompt-worker"},
    )

    assert resumed.status_code == 200
    assert marker.read_text(encoding="utf-8") == calls_before_recovery
    assert all(not (name.startswith("mcp.") and "prompt" in name) for name in model_tool_names)
    assert requests, resumed.body
    assert "[mcp_prompt] mcp-prompt.json" in requests[0][0].content
    assert "Untrusted MCP Prompt material" in requests[0][0].content
    assert "Rendered durable context" in requests[0][0].content
    assert requests[0][-1].content == "Apply the selected template."


def test_legacy_launch_has_no_prompt_attachment(tmp_path: Path) -> None:
    response = create_app(
        tmp_path / "sessions.sqlite", settings=_settings_without_mcp()
    ).create_session({"prompt": "Legacy task"})

    assert response.status_code == 201
    assert "mcp_prompt_id" not in response.body
    assert response.body["attachments"] == []


def _write_prompt_server(tmp_path: Path) -> Path:
    script = tmp_path / "server.py"
    script.write_text(
        dedent(
            r"""
            import json
            import sys
            from pathlib import Path

            marker = Path(sys.argv[1])
            for line in sys.stdin:
                request = json.loads(line)
                method = request.get("method")
                if method == "notifications/initialized":
                    continue
                marker.write_text(
                    (marker.read_text(encoding="utf-8") if marker.exists() else "")
                    + method + "\n",
                    encoding="utf-8",
                )
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"prompts": {}},
                        "serverInfo": {"name": "fixture", "version": "1"},
                    }
                elif method == "prompts/list":
                    result = {
                        "prompts": [{
                            "name": "durable",
                            "description": "Render durable context.",
                            "arguments": [{"name": "topic", "required": True}],
                        }]
                    }
                elif method == "prompts/get":
                    topic = request["params"]["arguments"]["topic"]
                    result = {"messages": [{
                        "role": "user",
                        "content": {"type": "text", "text": "Rendered " + topic},
                    }]}
                else:
                    result = {}
                response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
                print(json.dumps(response), flush=True)
            """
        ),
        encoding="utf-8",
    )
    return script


def _settings(database: Path, script: Path, marker: Path) -> ZebraAgentSettings:
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
                args=(str(script), str(marker)),
            ),
        ),
    )


def _settings_without_mcp() -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
