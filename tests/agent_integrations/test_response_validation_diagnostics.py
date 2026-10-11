"""Fixed parser diagnostics never expose arbitrary exception/provider text."""

from typing import Any

import pytest
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations import openai_payloads


def parse(payload: dict[str, Any]) -> None:
    openai_payloads.parse_completion(
        payload, provider_name="openai", default_model_name="test", latency_ms=1
    )


@pytest.mark.parametrize(
    ("payload", "rule"),
    [
        ({}, "choices_nonempty_list"),
        ({"choices": []}, "choices_nonempty_list"),
        ({"choices": [None]}, "choice_object"),
        ({"choices": [{}]}, "message_object"),
        ({"choices": [{"message": {"content": " "}}]}, "assistant_content_nonblank"),
        ({"choices": [{"message": {"tool_calls": "secret"}}]}, "tool_calls_list"),
        ({"choices": [{"message": {"tool_calls": [None]}}]}, "tool_call_object"),
        ({"choices": [{"message": {"tool_calls": [{}]}}]}, "tool_function_object"),
        (
            {"choices": [{"message": {"tool_calls": [{"function": {}}]}}]},
            "tool_function_name_nonblank",
        ),
        (
            {"choices": [{"message": {"tool_calls": [{"function": {"name": "tool"}}]}}]},
            "tool_call_id_nonblank",
        ),
        (
            {
                "choices": [{"message": {"content": "private"}}],
                "usage": {"prompt_tokens": "secret"},
            },
            "usage_token_integer",
        ),
        ({"choices": [{"message": {"content": "private"}}], "model": 42}, "optional_string_type"),
    ],
)
def test_native_parser_shape_matrix(payload: dict[str, Any], rule: str) -> None:
    for choice in payload.get("choices", []):
        if isinstance(choice, dict) and isinstance(choice.get("message"), dict):
            choice["message"]["role"] = "assistant"
    with pytest.raises(ModelResponseRejectedError) as caught:
        parse(payload)
    error = caught.value
    assert (error.reason, error.phase, error.retryable) == (
        "invalid_response_shape",
        "response_payload",
        True,
    )
    assert error.validation_rule == rule
    assert error.payload_size and error.payload_sha256
    assert "secret" not in str(error.metadata())
    assert "private" not in str(error)


@pytest.mark.parametrize("role", [None, "user", "tool", "secret"])
def test_nonassistant_role_is_rejected_with_static_diagnostic(role: str | None) -> None:
    with pytest.raises(ModelResponseRejectedError) as caught:
        parse({"choices": [{"message": {"role": role, "content": "private"}}]})
    assert caught.value.validation_rule == "assistant_role"
    assert "secret" not in str(caught.value.metadata())
    assert "private" not in str(caught.value.metadata())


@pytest.mark.parametrize("message,rule", openai_payloads._RESPONSE_VALIDATION_RULES.items())
def test_all_static_leaf_rules(monkeypatch: pytest.MonkeyPatch, message: str, rule: str) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise ValueError(message)

    monkeypatch.setattr(openai_payloads, "_parse_completion", reject)
    with pytest.raises(ModelResponseRejectedError) as caught:
        parse({})
    assert caught.value.validation_rule == rule


def test_unknown_exception_text_is_never_exported(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise ValueError("provider-private-token https://private.example/payload")

    monkeypatch.setattr(openai_payloads, "_parse_completion", reject)
    with pytest.raises(ModelResponseRejectedError) as caught:
        parse({"private_payload": "private-data"})
    assert caught.value.validation_rule == "response_payload_validation"
    assert "private" not in str(caught.value)
    assert "private" not in str(caught.value.metadata())
