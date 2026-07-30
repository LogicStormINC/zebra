import base64
import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import EventId, new_artifact_id, new_event_id, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import (
    ModelInputModality,
    ModelMediaCapabilities,
    ModelMediaInput,
    ModelMediaUnsupportedError,
    model_media_source_event_ids_metadata,
)
from agent_integrations import OpenAICompatibleModelGateway, build_model_gateway
from agent_integrations.openai_model_profiles import ModelProfile, resolve_model_profile
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_qwen_looking_model_without_profile_is_text_only() -> None:
    gateway = build_model_gateway(
        _settings(
            provider="qwen",
            model="qwen3.7-flash-2026-07-15",
        ),
        env={"TEST_API_KEY": "test-only-secret"},
    )

    assert ModelInputModality.IMAGE not in gateway.media_capabilities.input_modalities


@pytest.mark.parametrize(
    ("profile_id", "model", "images", "tools", "streaming", "max_images"),
    [
        ("qwen-flash-native-v1", "qwen3.7-flash-2026-07-15", True, True, True, 4),
        ("qwen-plus-native-v1", "qwen3.7-plus", True, False, False, 3),
        ("qwen-max-text-v1", "qwen3.7-max", False, False, False, 0),
    ],
)
def test_initial_profiles_declare_only_verified_media_capabilities(
    profile_id: str,
    model: str,
    images: bool,
    tools: bool,
    streaming: bool,
    max_images: int,
) -> None:
    capabilities = resolve_model_profile(profile_id, provider="qwen", model=model)

    assert (ModelInputModality.IMAGE in capabilities.input_modalities) is images
    assert capabilities.supports_tools_with_media is tools
    assert capabilities.supports_streaming_with_media is streaming
    assert capabilities.max_image_count == max_images


@pytest.mark.parametrize(
    ("profile_id", "provider", "model", "message"),
    [
        ("unknown-profile", "qwen", "qwen3.7-flash-2026-07-15", "unknown model profile"),
        (
            "qwen-flash-native-v1",
            "other-provider",
            "qwen3.7-flash-2026-07-15",
            "provider mismatch",
        ),
        ("qwen-flash-native-v1", "qwen", "other-model", "model mismatch"),
    ],
)
def test_invalid_profiles_fail_before_gateway_creation(
    profile_id: str,
    provider: str,
    model: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_model_gateway(
            _settings(provider=provider, model=model, profile_id=profile_id),
            env={"TEST_API_KEY": "test-only-secret"},
        )


def test_fixture_model_reaches_serializer_through_explicit_profile() -> None:
    captured: dict[str, object] = {}
    payload = b"fixture-image"
    source_event_id = new_event_id()
    capabilities = resolve_model_profile(
        "fixture-image-v1",
        provider="fixture-provider",
        model="opaque-model-name",
        profiles={
            "fixture-image-v1": ModelProfile(
                expected_provider="fixture-provider",
                expected_model="opaque-model-name",
                media_capabilities=ModelMediaCapabilities(
                    input_modalities=frozenset(
                        {ModelInputModality.TEXT, ModelInputModality.IMAGE}
                    ),
                    max_image_count=1,
                    max_image_bytes=1024,
                    max_total_image_bytes=1024,
                    image_media_types=frozenset({"image/png"}),
                ),
            )
        },
    )

    def handle(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "opaque-model-name",
                "choices": [{"message": {"role": "assistant", "content": "done"}}],
            },
        )

    gateway = OpenAICompatibleModelGateway(
        provider_name="fixture-provider",
        base_url="https://example.test",
        api_key="test-only-secret",
        model_name="opaque-model-name",
        media_capabilities=capabilities,
        media_resolver=_Resolver(payload),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    gateway.complete(
        [_user_message(source_event_id)],
        media_inputs=(_media("fixture", source_event_id=source_event_id, payload=payload),),
    )

    assert base64.b64encode(payload).decode("ascii") in json.dumps(captured)


def test_flash_profile_allows_media_with_tools_and_streaming_but_rejects_five_images() -> None:
    source_event_id = new_event_id()
    capabilities = resolve_model_profile(
        "qwen-flash-native-v1",
        provider="qwen",
        model="qwen3.7-flash-2026-07-15",
    )

    capabilities.validate_request(
        (_media("one", source_event_id=source_event_id),),
        has_tools=True,
        streaming=True,
    )
    with pytest.raises(ModelMediaUnsupportedError, match="image count"):
        capabilities.validate_request(
            tuple(
                _media(f"image-{index}", ordinal=index, source_event_id=source_event_id)
                for index in range(5)
            ),
            has_tools=True,
            streaming=True,
        )


def test_plus_and_max_profiles_fail_closed_for_unverified_media_combinations() -> None:
    source_event_id = new_event_id()
    media = (_media("image", source_event_id=source_event_id),)
    plus_capabilities = resolve_model_profile(
        "qwen-plus-native-v1",
        provider="qwen",
        model="qwen3.7-plus",
    )
    max_capabilities = resolve_model_profile(
        "qwen-max-text-v1",
        provider="qwen",
        model="qwen3.7-max",
    )

    plus_capabilities.validate_request(media, has_tools=False, streaming=False)
    with pytest.raises(ModelMediaUnsupportedError, match="tools"):
        plus_capabilities.validate_request(media, has_tools=True, streaming=False)
    with pytest.raises(ModelMediaUnsupportedError, match="streaming"):
        plus_capabilities.validate_request(media, has_tools=False, streaming=True)
    with pytest.raises(ModelMediaUnsupportedError, match="does not support image input"):
        max_capabilities.validate_request(media, has_tools=False, streaming=False)


@pytest.mark.parametrize(
    ("provider", "model"),
    [("deepseek", "deepseek-v4-flash"), ("text-provider", "text-model")],
)
def test_non_profiled_text_models_remain_text_only(provider: str, model: str) -> None:
    gateway = build_model_gateway(
        _settings(provider=provider, model=model),
        env={"TEST_API_KEY": "test-only-secret"},
    )

    assert gateway.media_capabilities == ModelMediaCapabilities()


def _settings(
    *,
    provider: str,
    model: str,
    profile_id: str | None = None,
) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider=provider,
            api_key_env="TEST_API_KEY",
            base_url="https://example.test/compatible-mode/v1",
            model=model,
            profile_id=profile_id,
        ),
    )


def _media(
    name: str,
    *,
    source_event_id: EventId,
    payload: bytes | None = None,
    ordinal: int = 0,
) -> ModelMediaInput:
    payload = payload or name.encode("utf-8")
    return ModelMediaInput(
        artifact_id=new_artifact_id(),
        media_type="image/png",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        display_name=name,
        ordinal=ordinal,
        source_message_id=source_event_id,
    )


def _user_message(source_event_id: EventId) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content="Describe the image.",
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
        metadata=model_media_source_event_ids_metadata((source_event_id,)),
    )


class _Resolver:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def resolve_media(self, media: ModelMediaInput) -> bytes:
        del media
        return self._payload
