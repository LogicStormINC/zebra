import base64
import hashlib
import os
import struct
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import EventId, new_artifact_id, new_event_id, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import (
    ModelMediaInput,
    model_media_source_event_ids,
    model_media_source_event_ids_metadata,
)
from agent_integrations import ModelProviderError, build_model_gateway
from zebra_agent_config import load_settings

_SMOKE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGNQjlhAEmIY1TCqYfhqAAD3YBsQX4WS9AAAAABJRU5ErkJggg=="
)


def test_smoke_image_fixture_exceeds_qwen_minimum_dimensions() -> None:
    width, height = struct.unpack(">II", _SMOKE_PNG[16:24])

    assert min(width, height) > 10


def test_real_qwen_native_image_smoke() -> None:
    if os.environ.get("ZEBRA_QWEN_NATIVE_SMOKE") != "1":
        pytest.skip("set ZEBRA_QWEN_NATIVE_SMOKE=1 with private DashScope configuration")
    settings = load_settings()
    assert settings.model.provider == "qwen"
    assert settings.model.api_key_env == "DASHSCOPE_API_KEY"
    gateway = build_model_gateway(
        settings,
        media_resolver=_OneImageResolver(_SMOKE_PNG),
    )
    source_message_id = new_event_id()
    media = ModelMediaInput(
        artifact_id=new_artifact_id(),
        media_type="image/png",
        sha256=hashlib.sha256(_SMOKE_PNG).hexdigest(),
        size_bytes=len(_SMOKE_PNG),
        display_name="qwen-smoke.png",
        ordinal=0,
        source_message_id=source_message_id,
    )
    try:
        completion = gateway.complete(
            [
                _smoke_user_message(source_message_id)
            ],
            media_inputs=(media,),
        )
    except ModelProviderError as error:
        raise AssertionError(
            f"Qwen native smoke failed: {error.normalized_error}"
        ) from None

    assert completion.call_metadata.provider == "qwen"
    assert completion.assistant_message.content.strip()


def test_smoke_user_message_declares_its_media_source_event() -> None:
    source_message_id = new_event_id()

    assert model_media_source_event_ids(_smoke_user_message(source_message_id).metadata) == (
        source_message_id,
    )


def _smoke_user_message(source_message_id: EventId) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content="Reply with a short description of this image.",
        created_at=datetime.now(UTC),
        metadata=model_media_source_event_ids_metadata((source_message_id,)),
    )


class _OneImageResolver:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def resolve_media(self, _media: ModelMediaInput) -> bytes:
        return self._payload
