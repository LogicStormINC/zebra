from __future__ import annotations

from datetime import UTC, datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_integrations.deepseek_responses_payloads import serialize_input
from agent_integrations.openai_payloads import serialize_message


def _message() -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content="分析这张图",
        created_at=datetime.now(UTC),
        provider_image_data_urls=("data:image/png;base64,ZmFrZS1wbmc=",),
    )


def test_chat_completions_serializes_native_image_block() -> None:
    payload = serialize_message(_message(), include_provider_reasoning=True)

    assert payload["content"] == [
        {"type": "text", "text": "分析这张图"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,ZmFrZS1wbmc=", "detail": "auto"},
        },
    ]


def test_responses_serializes_native_input_image_block() -> None:
    _, items = serialize_input([_message()])

    assert items[0]["content"] == [
        {"type": "input_text", "text": "分析这张图"},
        {
            "type": "input_image",
            "image_url": "data:image/png;base64,ZmFrZS1wbmc=",
            "detail": "auto",
        },
    ]
