"""Actual provider requests prove Bundle configuration is consumed."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelInvocationPolicy
from agent_integrations.bundle_model import BundleModelGateway

from tests.test_bundle_assembly import approved_assembly, settings


def message():
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content="Test",
        created_at=datetime.now(UTC),
    )


def test_actual_chat_body_uses_frozen_model_limits_temperature_and_credentials(monkeypatch):
    assembly, _ = approved_assembly(settings())
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-provider-credential")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = BundleModelGateway(assembly, client=client)
        assert gateway.context_window.context_tokens == 128000
        gateway.complete(
            [message()], invocation_policy=ModelInvocationPolicy(max_output_tokens=123)
        )
        body = json.loads(requests[0].content)
        assert body["model"] == "alpha" and body["max_tokens"] == 123
        assert body["temperature"] == 0.25
        assert requests[0].url == "https://models.example/v1/chat/completions"
        assert requests[0].headers["Authorization"] == "Bearer private-provider-credential"
        gateway.complete(
            [message()], invocation_policy=ModelInvocationPolicy(max_output_tokens=99999)
        )
        assert json.loads(requests[1].content)["max_tokens"] == 2048
    assert "private-provider-credential" not in assembly.model_dump_json()


def test_stream_and_policy_refusal_use_same_frozen_parameters(monkeypatch):
    assembly, _ = approved_assembly(settings(), model="beta")
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private")
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        event = {"choices": [{"index": 0, "delta": {"content": "OK"}, "finish_reason": None}]}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n",
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = BundleModelGateway(assembly, client=client)
        gateway.complete_stream([message()], on_text_delta=lambda _: None)
        assert bodies[0]["model"] == "beta" and bodies[0]["max_tokens"] == 2048
        with pytest.raises(ValueError, match="INCOMPATIBLE_BUNDLE_MODEL_POLICY"):
            gateway.complete(
                [message()], invocation_policy=ModelInvocationPolicy(profile_id="latest")
            )
        assert len(bodies) == 1
        with pytest.raises(ValueError):
            gateway.prepare_text_request([message()], invocation_policy=ModelInvocationPolicy())
