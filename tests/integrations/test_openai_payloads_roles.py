"""Wire roles are checked before a provider message becomes an assistant message."""

import pytest
from agent_core.domain.messages import MessageRole
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations.openai_payloads import parse_completion


@pytest.mark.parametrize("role", ["user", "system", "tool", "Assistant", "", None, 1, [], {}])
def test_completion_requires_exact_assistant_wire_role(role):
    with pytest.raises(ModelResponseRejectedError) as rejected:
        parse_completion(
            {"choices": [{"message": {"role": role, "content": "ordinary text"}}]},
            provider_name="openai",
            default_model_name="model",
            latency_ms=1,
        )
    assert rejected.value.reason == "invalid_response_shape"
    assert "role" in str(rejected.value.__cause__)


def test_completion_rejects_missing_wire_role():
    with pytest.raises(ModelResponseRejectedError) as rejected:
        parse_completion(
            {"choices": [{"message": {"content": "ordinary text"}}]},
            provider_name="openai",
            default_model_name="model",
            latency_ms=1,
        )
    assert "role" in str(rejected.value.__cause__)


def test_valid_assistant_wire_role_preserves_text_and_usage():
    result = parse_completion(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ordinary text"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        },
        provider_name="openai",
        default_model_name="model",
        latency_ms=1,
    )
    assert result.assistant_message.role is MessageRole.ASSISTANT
    assert result.assistant_message.content == "ordinary text"
    assert result.call_metadata.usage.total_tokens == 5
