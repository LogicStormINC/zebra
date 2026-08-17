import json
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import ModelMediaCapabilities
from agent_integrations import build_model_gateway
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


@pytest.mark.parametrize(
    ("profile_id", "model", "enable_thinking"),
    [
        ("qwen-max-text-v1", "qwen3.7-max", True),
        ("qwen-max-dated-thinking-v1", "qwen3.7-max-2026-05-17", True),
        ("qwen-max-dated-20260520-thinking-v1", "qwen3.7-max-2026-05-20", True),
        ("qwen-max-preview-thinking-v1", "qwen3.7-max-preview", True),
    ],
)
def test_qwen_max_profile_controls_thinking_without_native_media(
    profile_id: str,
    model: str,
    enable_thinking: bool,
) -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"role": "assistant", "content": "OK"}}],
            },
        )

    gateway = build_model_gateway(
        _settings(model=model, profile_id=profile_id),
        env={"TEST_API_KEY": "test-only-secret"},
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    gateway.complete(
        [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content="Reply OK.",
                created_at=datetime(2026, 8, 15, tzinfo=UTC),
            )
        ]
    )

    assert gateway.media_capabilities == ModelMediaCapabilities()
    assert captured["body"]["enable_thinking"] is enable_thinking


def test_qwen_thinking_profile_rejects_model_identity_drift() -> None:
    with pytest.raises(ValueError, match="model mismatch"):
        build_model_gateway(
            _settings(
                model="qwen3.7-max",
                profile_id="qwen-max-preview-thinking-v1",
            ),
            env={"TEST_API_KEY": "test-only-secret"},
        )


def _settings(*, model: str, profile_id: str) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="qwen",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test/compatible-mode/v1",
            model=model,
            profile_id=profile_id,
        ),
    )
