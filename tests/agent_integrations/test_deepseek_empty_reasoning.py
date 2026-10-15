"""Empty final reasoning is a returned field, not missing continuation."""

import json

import httpx
import pytest
from agent_core.domain.messages import MessageRole
from agent_core.domain.modeling import ModelInvocationPolicy, ModelThinkingMode

from tests.agent_integrations.test_deepseek_specialization import _gateway, _message, _tool


@pytest.mark.parametrize("streaming", [False, True])
def test_empty_final_reasoning_survives_same_turn_quality_revision(streaming: bool) -> None:
    requests: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 2:
            candidate = body["messages"][-2]
            assert candidate["role"] == "assistant"
            if candidate.get("reasoning_content") != "":
                return httpx.Response(400, json={"error": {
                    "message": "The `reasoning_content` in the thinking mode must be passed back"
                }})
        if body["stream"]:
            return httpx.Response(200, text=(
                'data: {"choices":[{"delta":{"reasoning_content":"","content":"2"}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                'data: [DONE]\n\n'
            ), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": "2", "reasoning_content": ""
        }, "finish_reason": "stop"}]})

    gateway = _gateway(handle)
    policy = ModelInvocationPolicy(thinking_mode=ModelThinkingMode.ENABLED)
    user = _message("Only return the command output")
    tools = (_tool(),)

    def complete(messages):
        if streaming:
            return gateway.complete_stream(
                messages, tools=tools, invocation_policy=policy, on_text_delta=lambda _: None
            )
        return gateway.complete(messages, tools=tools, invocation_policy=policy)

    first = complete([user])
    feedback = _message("Keep the result and revise its presentation").model_copy(
        update={"role": MessageRole.SYSTEM, "metadata": {"runtime_feedback": True}}
    )
    final = complete([user, first.assistant_message, feedback])
    assert final.assistant_message.content == "2"
    assert first.assistant_message.provider_reasoning_content == ""
    assert first.assistant_message.metadata["provider_reasoning_required"] is True
    assert "provider_reasoning_content" not in first.assistant_message.model_dump(mode="json")
    assert len(requests) == 2
