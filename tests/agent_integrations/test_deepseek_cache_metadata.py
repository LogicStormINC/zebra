from datetime import UTC, datetime

import httpx
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_integrations import OpenAICompatibleModelGateway


def test_request_metadata_locates_the_first_changed_message() -> None:
    gateway = _gateway()
    first = gateway.complete([_message("stable"), _message("old tail")])
    second = gateway.complete([_message("stable"), _message("new tail")])

    assert first.call_metadata.message_prefix_hashes[0] == (
        second.call_metadata.message_prefix_hashes[0]
    )
    assert first.call_metadata.message_prefix_hashes[1] != (
        second.call_metadata.message_prefix_hashes[1]
    )
    assert first.call_metadata.request_hash != second.call_metadata.request_hash


def test_stable_prefix_ignores_deferred_system_context() -> None:
    gateway = _gateway()
    stable = _message("stable", role=MessageRole.SYSTEM)
    history = _message("history")
    first = gateway.complete(
        [stable, history, _message("dynamic-a", role=MessageRole.SYSTEM)]
    )
    second = gateway.complete(
        [stable, history, _message("dynamic-b", role=MessageRole.SYSTEM)]
    )

    assert first.call_metadata.stable_prefix_hash == second.call_metadata.stable_prefix_hash
    assert first.call_metadata.request_hash != second.call_metadata.request_hash


def _gateway() -> OpenAICompatibleModelGateway:
    return OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "model": "deepseek-v4-flash",
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "done"},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                )
            )
        ),
    )


def _message(content: str, *, role: MessageRole = MessageRole.USER) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
