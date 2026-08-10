from pathlib import Path

import pytest
import zebra_agent_cli.cli as cli_module
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelUsage,
)
from agent_core.domain.tools import ToolCall
from agent_integrations import ModelProviderSettings
from cli_run_support import (
    FakeGateway,
    _created_at,
    _settings,
)
from zebra_agent_cli.cli import execute
from zebra_agent_config import ZebraAgentSettings


def test_cli_model_command_uses_configured_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_model_gateway(settings: ModelProviderSettings) -> FakeGateway:
        assert settings.provider == "test"
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Gateway response",
                    created_at=_created_at(),
                ),
                call_metadata=ModelCallMetadata(
                    provider="test",
                    model_name="test-model",
                    latency_ms=42,
                    usage=ModelUsage(
                        input_tokens=3,
                        output_tokens=5,
                        total_tokens=8,
                    ),
                ),
            )
        )

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)

    result = execute(["model", "Hello"], settings=_settings(Path(":memory:")))

    assert result.command == "model"
    assert result.payload == {
        "prompt": "Hello",
        "response": "Gateway response",
        "provider": "test",
        "model_name": "test-model",
        "latency_ms": 42,
        "input_tokens": 3,
        "output_tokens": 5,
        "total_tokens": 8,
        "tool_calls": [],
    }

def test_cli_model_command_reports_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Tool calls proposed.",
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
        )

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)

    result = execute(["model", "Read the README"], settings=_settings(Path(":memory:")))

    assert result.payload["tool_calls"] == [
        {
            "name": "files.read",
            "arguments": {"path": "README.md"},
        }
    ]

def test_cli_model_command_surfaces_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        raise ValueError("missing API key in environment variable TEST_API_KEY")

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)

    with pytest.raises(ValueError, match="missing API key"):
        execute(["model", "Hello"], settings=_settings(Path(":memory:")))
