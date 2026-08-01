import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import EventId, new_artifact_id, new_event_id, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import (
    MODEL_MEDIA_SOURCE_EVENT_IDS_METADATA_KEY,
    ModelInputModality,
    ModelMediaCapabilities,
    ModelMediaInput,
    ModelMediaUnsupportedError,
    model_media_source_event_ids_metadata,
)
from agent_core.domain.modeling import (
    ModelToolDefinition,
)
from agent_integrations import ModelProviderError, OpenAICompatibleModelGateway, build_model_gateway
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_qwen_serializes_any_number_of_images_in_ordinal_order_with_typed_tools() -> None:
    captured: dict[str, object] = {}
    payloads = {
        "second": b"second-image",
        "first": b"first-image",
        "third": b"third-image",
        "fourth": b"fourth-image",
    }

    def handle(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "qwen3.7-flash-2026-07-15",
                "choices": [{"message": {"role": "assistant", "content": "Done."}}],
            },
        )

    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        media_capabilities=_qwen_capabilities(),
        media_resolver=_Resolver(payloads),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    tool = ModelToolDefinition(
        name="files.read",
        description="Read one file.",
        parameters={"type": "object", "properties": {}},
    )
    source_event_id = new_event_id()
    media = (
        _media(
            "third", ordinal=30, payload=payloads["third"], source_message_id=source_event_id
        ),
        _media(
            "first", ordinal=10, payload=payloads["first"], source_message_id=source_event_id
        ),
        _media(
            "fourth", ordinal=40, payload=payloads["fourth"], source_message_id=source_event_id
        ),
        _media(
            "second", ordinal=20, payload=payloads["second"], source_message_id=source_event_id
        ),
    )

    gateway.complete(
        [_user_message("Compare these images.", source_event_ids=(source_event_id,))],
        tools=(tool,),
        media_inputs=media,
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["enable_thinking"] is False
    assert body["enable_search"] is False
    assert body["enable_code_interpreter"] is False
    assert body["tools"][0]["function"]["name"] == "files__read"
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Compare these images."}
    assert [part["image_url"]["url"] for part in parts[1:]] == [
        _data_url(payloads[name]) for name in ("first", "second", "third", "fourth")
    ]


def test_qwen_streams_media_with_typed_tools_enabled() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text=(
                'data: {"model":"qwen3.7-flash-2026-07-15","choices":'
                '[{"delta":{"content":"Native "}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"media"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        media_capabilities=_qwen_capabilities(),
        media_resolver=_Resolver({"stream": b"stream-image"}),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    deltas = []

    source_event_id = new_event_id()
    result = gateway.complete_stream(
        [_user_message("Describe the image.", source_event_ids=(source_event_id,))],
        tools=(
            ModelToolDefinition(
                name="files.read",
                description="Read one file.",
                parameters={"type": "object", "properties": {}},
            ),
        ),
        media_inputs=(
            _media(
                "stream",
                ordinal=1,
                payload=b"stream-image",
                source_message_id=source_event_id,
            ),
        ),
        on_text_delta=deltas.append,
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["stream"] is True
    assert body["enable_thinking"] is False
    assert body["enable_search"] is False
    assert body["enable_code_interpreter"] is False
    assert body["stream_options"] == {"include_usage": True}
    assert [delta.content for delta in deltas] == ["Native ", "media"]
    assert result.assistant_message.content == "Native media"


def test_qwen_attaches_each_image_to_its_source_user_message_in_ordinal_order() -> None:
    captured: dict[str, object] = {}
    payloads = {
        "first-late": b"first-late-image",
        "first-early": b"first-early-image",
        "second": b"second-image",
    }

    def handle(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "qwen3.7-flash-2026-07-15",
                "choices": [{"message": {"role": "assistant", "content": "Done."}}],
            },
        )

    first_source_event_id = new_event_id()
    second_source_event_id = new_event_id()
    first_user = _user_message(
        "Compare the first pair.", source_event_ids=(first_source_event_id,)
    )
    second_user = _user_message(
        "Now inspect the second image.", source_event_ids=(second_source_event_id,)
    )
    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        media_capabilities=_qwen_capabilities(),
        media_resolver=_Resolver(payloads),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    gateway.complete(
        [
            first_user,
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="I will compare them.",
                created_at=datetime(2026, 7, 30, tzinfo=UTC),
            ),
            second_user,
        ],
        media_inputs=(
            _media(
                "first-late",
                ordinal=20,
                payload=payloads["first-late"],
                source_message_id=first_source_event_id,
            ),
            _media(
                "second",
                ordinal=30,
                payload=payloads["second"],
                source_message_id=second_source_event_id,
            ),
            _media(
                "first-early",
                ordinal=10,
                payload=payloads["first-early"],
                source_message_id=first_source_event_id,
            ),
        ),
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert MODEL_MEDIA_SOURCE_EVENT_IDS_METADATA_KEY not in json.dumps(body)
    assert str(first_source_event_id) not in json.dumps(body)
    assert str(second_source_event_id) not in json.dumps(body)
    first_parts = body["messages"][0]["content"]
    second_parts = body["messages"][2]["content"]
    assert first_parts[0] == {"type": "text", "text": "Compare the first pair."}
    assert [part["image_url"]["url"] for part in first_parts[1:]] == [
        _data_url(payloads["first-early"]),
        _data_url(payloads["first-late"]),
    ]
    assert second_parts == [
        {"type": "text", "text": "Now inspect the second image."},
        {"type": "image_url", "image_url": {"url": _data_url(payloads["second"])}},
    ]


def test_qwen_rejects_media_when_its_source_user_message_is_not_in_the_request() -> None:
    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        media_capabilities=_qwen_capabilities(),
        media_resolver=_Resolver({"orphan": b"orphan-image"}),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("orphaned media must not reach transport")
            )
        ),
    )

    with pytest.raises(ModelMediaUnsupportedError, match="source user message"):
        gateway.complete(
            [_user_message("Describe the available image.")],
            media_inputs=(_media("orphan", ordinal=0, payload=b"orphan-image"),),
        )


def test_qwen_rejects_media_when_its_source_user_message_is_ambiguous() -> None:
    source_event_id = new_event_id()
    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        media_capabilities=_qwen_capabilities(),
        media_resolver=_Resolver({"shared": b"shared-image"}),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("ambiguous media must not reach transport")
            )
        ),
    )

    with pytest.raises(ModelMediaUnsupportedError, match="source user message is ambiguous"):
        gateway.complete(
            [
                _user_message("First description.", source_event_ids=(source_event_id,)),
                _user_message("Second description.", source_event_ids=(source_event_id,)),
            ],
            media_inputs=(
                _media(
                    "shared",
                    ordinal=0,
                    payload=b"shared-image",
                    source_message_id=source_event_id,
                ),
            ),
        )


def test_text_only_provider_rejects_media_before_transport() -> None:
    gateway = OpenAICompatibleModelGateway(
        provider_name="text-only",
        base_url="https://example.test",
        api_key="test-only-secret",
        model_name="text-only",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("text-only provider must not receive media")
            )
        ),
    )

    with pytest.raises(ValueError, match="does not support image input"):
        gateway.complete(
            [_user_message("Describe the image.")],
            media_inputs=(_media("blocked", ordinal=1),),
        )


def test_qwen_flash_profile_reads_only_dashscope_api_key() -> None:
    settings = ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="qwen",
            api_key_env="DASHSCOPE_API_KEY",
            base_url="https://qwen.example.test/compatible-mode/v1",
            model="qwen3.7-flash-2026-07-15",
            profile_id="qwen-flash-native-v1",
        ),
    )

    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        build_model_gateway(settings, env={"QWEN_API_KEY": "must-not-be-used"})
    gateway = build_model_gateway(settings, env={"DASHSCOPE_API_KEY": "test-only-secret"})

    assert ModelInputModality.IMAGE in gateway.media_capabilities.input_modalities


def test_qwen_rejects_unsupported_or_oversize_media_before_transport() -> None:
    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        media_capabilities=_qwen_capabilities(),
        media_resolver=_Resolver({}),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("unsupported media must not reach transport")
            )
        ),
    )
    image = _media("too-large", ordinal=0)

    with pytest.raises(ValueError, match="image count"):
        gateway.complete(
            [_user_message("Describe the images.")],
            media_inputs=tuple(_media(f"image-{index}", ordinal=index) for index in range(5)),
        )
    with pytest.raises(ValueError, match="per-image"):
        gateway.complete(
            [_user_message("Describe the image.")],
            media_inputs=(replace(image, size_bytes=5 * 1024 * 1024 + 1),),
        )
    with pytest.raises(ValueError, match="media type"):
        gateway.complete(
            [_user_message("Describe the image.")],
            media_inputs=(replace(image, media_type="image/gif"),),
        )


def test_qwen_normalizes_http_errors_without_retaining_the_request_details() -> None:
    gateway = OpenAICompatibleModelGateway(
        provider_name="qwen",
        base_url="https://private.example.test/compatible-mode/v1",
        api_key="test-only-secret",
        model_name="qwen3.7-flash-2026-07-15",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(401, request=request))
        ),
    )

    with pytest.raises(ModelProviderError) as caught:
        gateway.complete([_user_message("Describe the image.")])

    assert caught.value.normalized_error == "authentication_failed"
    assert caught.value.__cause__ is None
    assert "private.example.test" not in str(caught.value)


def test_qwen_text_model_rejects_media_without_an_explicit_native_profile() -> None:
    settings = ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="qwen",
            api_key_env="DASHSCOPE_API_KEY",
            base_url="https://example.test/compatible-mode/v1",
            model="qwen-text-only",
        ),
    )
    gateway = build_model_gateway(
        settings,
        env={"DASHSCOPE_API_KEY": "test-only-secret"},
        media_resolver=_Resolver({}),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("text-only Qwen must not receive media")
            )
        ),
    )

    with pytest.raises(ModelMediaUnsupportedError, match="does not support image input"):
        gateway.complete(
            [_user_message("Describe the image.")],
            media_inputs=(_media("blocked", ordinal=0),),
        )


def _qwen_capabilities() -> ModelMediaCapabilities:
    return ModelMediaCapabilities(
        input_modalities=frozenset({ModelInputModality.TEXT, ModelInputModality.IMAGE}),
        supports_tools_with_media=True,
        supports_streaming_with_media=True,
        max_image_count=4,
        max_image_bytes=5 * 1024 * 1024,
        max_total_image_bytes=20 * 1024 * 1024,
        image_media_types=frozenset({"image/jpeg", "image/png"}),
    )


def _media(
    name: str,
    *,
    ordinal: int,
    payload: bytes | None = None,
    source_message_id: EventId | None = None,
) -> ModelMediaInput:
    payload = payload or name.encode("utf-8")
    return ModelMediaInput(
        artifact_id=new_artifact_id(),
        media_type="image/png",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        display_name=name,
        ordinal=ordinal,
        source_message_id=source_message_id or new_event_id(),
    )


def _user_message(
    content: str,
    *,
    source_event_ids: tuple[EventId, ...] = (),
) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
        metadata=model_media_source_event_ids_metadata(source_event_ids),
    )


def _data_url(payload: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(payload).decode('ascii')}"


class _Resolver:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = payloads

    def resolve_media(self, media: ModelMediaInput) -> bytes:
        return self._payloads[media.display_name]
