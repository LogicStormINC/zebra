from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from agent_core.domain.identifiers import ArtifactId, EventId

MODEL_MEDIA_SOURCE_EVENT_IDS_METADATA_KEY = "model_media_source_event_ids"


class ModelInputModality(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class ModelMediaUnsupportedError(ValueError):
    """A model request includes media outside the selected profile contract."""


@dataclass(frozen=True)
class ModelMediaInput:
    artifact_id: ArtifactId
    media_type: str
    sha256: str
    size_bytes: int
    display_name: str
    ordinal: int
    source_message_id: EventId

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, UUID) or not isinstance(self.source_message_id, UUID):
            raise ValueError("model media references must use UUID identifiers")
        media_type = self.media_type.strip().lower()
        if "/" not in media_type or any(character.isspace() for character in media_type):
            raise ValueError("model media_type must be a normalized MIME type")
        if self.size_bytes <= 0:
            raise ValueError("model media size_bytes must be positive")
        digest = self.sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("model media sha256 must be a 64-character hex digest")
        display_name = self.display_name.strip()
        if not display_name or any(character in display_name for character in ("/", "\\")):
            raise ValueError("model media display_name must be a safe basename")
        if self.ordinal < 0:
            raise ValueError("model media ordinal must not be negative")
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "display_name", display_name)


@dataclass(frozen=True)
class ModelMediaCapabilities:
    input_modalities: frozenset[ModelInputModality] = frozenset({ModelInputModality.TEXT})
    supports_tools_with_media: bool = False
    supports_streaming_with_media: bool = False
    max_image_count: int = 0
    max_image_bytes: int = 0
    max_total_image_bytes: int = 0
    image_media_types: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if any(not isinstance(modality, ModelInputModality) for modality in self.input_modalities):
            raise ValueError("model input modalities must be ModelInputModality values")
        if ModelInputModality.TEXT not in self.input_modalities:
            raise ValueError("model input capabilities must include text")
        normalized_types = frozenset(
            media_type.strip().lower() for media_type in self.image_media_types
        )
        if any(not media_type or "/" not in media_type for media_type in normalized_types):
            raise ValueError("model image media types must be normalized MIME types")
        limits = (self.max_image_count, self.max_image_bytes, self.max_total_image_bytes)
        if any(limit < 0 for limit in limits):
            raise ValueError("model image limits must not be negative")
        supports_images = ModelInputModality.IMAGE in self.input_modalities
        if supports_images:
            if not all(limits) or not normalized_types:
                raise ValueError("image-capable models require positive limits and media types")
        elif (
            any(limits)
            or normalized_types
            or self.supports_tools_with_media
            or self.supports_streaming_with_media
        ):
            raise ValueError("text-only models must not declare image capabilities")
        object.__setattr__(self, "image_media_types", normalized_types)

    def validate_request(
        self,
        media_inputs: tuple[ModelMediaInput, ...],
        *,
        has_tools: bool,
        streaming: bool,
    ) -> None:
        if not media_inputs:
            return
        if ModelInputModality.IMAGE not in self.input_modalities:
            raise ModelMediaUnsupportedError("model profile does not support image input")
        if len(media_inputs) > self.max_image_count:
            raise ModelMediaUnsupportedError("model request exceeds image count limit")
        if has_tools and not self.supports_tools_with_media:
            raise ModelMediaUnsupportedError(
                "model profile does not support tools with image input"
            )
        if streaming and not self.supports_streaming_with_media:
            raise ModelMediaUnsupportedError(
                "model profile does not support streaming with image input"
            )
        if len({media.ordinal for media in media_inputs}) != len(media_inputs):
            raise ModelMediaUnsupportedError("model media ordinals must be unique")
        if len({media.artifact_id for media in media_inputs}) != len(media_inputs):
            raise ModelMediaUnsupportedError("model media artifact references must be unique")
        total_bytes = sum(media.size_bytes for media in media_inputs)
        if total_bytes > self.max_total_image_bytes:
            raise ModelMediaUnsupportedError("model request exceeds aggregate image byte limit")
        for media in media_inputs:
            if media.media_type not in self.image_media_types:
                raise ModelMediaUnsupportedError("model profile does not support image media type")
            if media.size_bytes > self.max_image_bytes:
                raise ModelMediaUnsupportedError("model request exceeds per-image byte limit")


def ordered_media_inputs(media_inputs: tuple[ModelMediaInput, ...]) -> tuple[ModelMediaInput, ...]:
    return tuple(sorted(media_inputs, key=lambda media: media.ordinal))


def model_media_source_event_ids_metadata(
    source_event_ids: Iterable[EventId],
) -> dict[str, object]:
    ordered_ids = tuple(dict.fromkeys(str(source_event_id) for source_event_id in source_event_ids))
    return (
        {MODEL_MEDIA_SOURCE_EVENT_IDS_METADATA_KEY: ordered_ids}
        if ordered_ids
        else {}
    )


def model_media_source_event_ids(metadata: Mapping[str, object]) -> tuple[EventId, ...]:
    value = metadata.get(MODEL_MEDIA_SOURCE_EVENT_IDS_METADATA_KEY)
    if not isinstance(value, tuple | list):
        return ()
    source_event_ids: list[EventId] = []
    for item in value:
        if isinstance(item, UUID):
            source_event_id = EventId(item)
        elif isinstance(item, str):
            try:
                source_event_id = EventId(UUID(item))
            except ValueError:
                return ()
        else:
            return ()
        source_event_ids.append(source_event_id)
    if len(set(source_event_ids)) != len(source_event_ids):
        return ()
    return tuple(source_event_ids)
