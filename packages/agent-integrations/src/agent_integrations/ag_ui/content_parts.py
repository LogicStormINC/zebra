"""Project governed Artifact presentation into replayable rich-content parts."""

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from ag_ui.core import CustomEvent

_INLINE_IMAGE_TYPES = frozenset(
    {"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"}
)
_INLINE_VIDEO_TYPES = frozenset({"video/mp4", "video/ogg", "video/webm"})
_VEGA_LITE_TYPES = frozenset({"application/vnd.vegalite+json", "application/vnd.vegalite.v6+json"})


_PART_TYPES = frozenset({"image", "video", "chart", "file"})
_ARTIFACT_KEYS = frozenset(
    {
        "artifactId",
        "thumbnailArtifactId",
        "posterArtifactId",
        "captionsArtifactId",
        "transcriptArtifactId",
        "specArtifactId",
        "dataArtifactId",
        "fallbackImageArtifactId",
        "fallbackTableArtifactId",
    }
)
_COMMON_KEYS = frozenset({"id", "type", "state"})
_KEYS_BY_TYPE = {
    "image": _COMMON_KEYS
    | frozenset(
        {
            "alt",
            "artifactId",
            "fileName",
            "height",
            "mimeType",
            "sizeBytes",
            "thumbnailArtifactId",
            "width",
        }
    ),
    "video": _COMMON_KEYS
    | frozenset(
        {
            "artifactId",
            "captionsArtifactId",
            "captionsLanguage",
            "description",
            "durationMs",
            "fileName",
            "height",
            "mimeType",
            "posterArtifactId",
            "sizeBytes",
            "title",
            "transcriptArtifactId",
            "width",
        }
    ),
    "chart": _COMMON_KEYS
    | frozenset(
        {
            "dataArtifactId",
            "description",
            "fallbackImageArtifactId",
            "fallbackTableArtifactId",
            "specArtifactId",
            "specType",
            "specVersion",
            "title",
        }
    ),
    "file": _COMMON_KEYS
    | frozenset({"artifactId", "fileName", "mimeType", "sizeBytes", "description", "name"}),
}


def project_content_parts(
    payload: Mapping[str, Any],
    *,
    tool_call_id: str,
    timestamp: int,
) -> tuple[CustomEvent, ...]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("delivery") is not True:
        return ()
    explicit = metadata.get("content_parts")
    if explicit is not None:
        if metadata.get("schema_version") != "2" or not _valid_explicit_parts(explicit):
            return ()
        return tuple(
            CustomEvent(
                timestamp=timestamp,
                name="zebra.content_part",
                value={
                    "index": index,
                    "part": dict(part),
                    "schema_version": "2",
                    "tool_call_id": tool_call_id,
                },
            )
            for index, part in enumerate(explicit)
        )
    legacy = _legacy_content_part(metadata, tool_call_id=tool_call_id)
    if legacy is None:
        return ()
    return (
        CustomEvent(
            timestamp=timestamp,
            name="zebra.content_part",
            value={"part": legacy, "schema_version": "1", "tool_call_id": tool_call_id},
        ),
    )


def project_content_part(
    payload: Mapping[str, Any], *, tool_call_id: str, timestamp: int
) -> CustomEvent | None:
    """Compatibility wrapper for the original single-Part projection."""

    projected = project_content_parts(payload, tool_call_id=tool_call_id, timestamp=timestamp)
    return projected[0] if len(projected) == 1 else None


def _legacy_content_part(
    metadata: Mapping[str, Any], *, tool_call_id: str
) -> dict[str, object] | None:
    artifact_uri = metadata.get("artifact_uri")
    file_name = metadata.get("file_name")
    mime_type = metadata.get("mime_type")
    size_bytes = metadata.get("size_bytes")
    if not (
        isinstance(artifact_uri, str)
        and artifact_uri.startswith("artifact://")
        and isinstance(file_name, str)
        and file_name.strip()
        and isinstance(mime_type, str)
        and mime_type.strip()
        and isinstance(size_bytes, int)
        and size_bytes >= 0
    ):
        return None
    artifact_id = artifact_uri.removeprefix("artifact://")
    return _part_for_artifact(
        artifact_id=artifact_id,
        file_name=file_name.strip(),
        mime_type=mime_type.strip().lower(),
        size_bytes=size_bytes,
        tool_call_id=tool_call_id,
    )


def _valid_explicit_parts(value: object) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        return False
    try:
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) > 32_768:
            return False
    except (TypeError, ValueError):
        return False
    return all(_valid_explicit_part(part) for part in value)


def _valid_explicit_part(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    kind = value.get("type")
    if kind not in _PART_TYPES or set(value) - _KEYS_BY_TYPE[str(kind)]:
        return False
    if not _text(value.get("id"), 600) or value.get("state") not in {
        "processing",
        "ready",
        "failed",
    }:
        return False
    required = {
        "image": ("artifactId", "mimeType", "alt"),
        "video": ("artifactId", "mimeType", "title"),
        "chart": ("specArtifactId", "specType", "specVersion", "title", "description"),
        "file": ("artifactId", "mimeType", "name"),
    }[str(kind)]
    if any(not _text(value.get(key), 2_000) for key in required):
        return False
    if kind == "chart" and (
        value.get("specType") != "vega-lite" or value.get("specVersion") != "6"
    ):
        return False
    for key in _ARTIFACT_KEYS & set(value):
        if not _uuid(value.get(key)):
            return False
    for key in ("sizeBytes", "durationMs"):
        if key in value and not _integer(value[key], minimum=0):
            return False
    for key in ("width", "height"):
        if key in value and not _integer(value[key], minimum=1, maximum=16_384):
            return False
    return True


def _text(value: object, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


def _integer(value: object, *, minimum: int, maximum: int | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return False
    return maximum is None or value <= maximum


def _part_for_artifact(
    *, artifact_id: str, file_name: str, mime_type: str, size_bytes: int, tool_call_id: str
) -> dict[str, object]:
    common: dict[str, object] = {
        "artifactId": artifact_id,
        "fileName": file_name,
        "id": f"content:{tool_call_id}:{artifact_id}",
        "mimeType": mime_type,
        "sizeBytes": size_bytes,
        "state": "ready",
    }
    if mime_type in _INLINE_IMAGE_TYPES:
        return {**common, "alt": file_name, "type": "image"}
    if mime_type in _INLINE_VIDEO_TYPES:
        return {**common, "title": file_name, "type": "video"}
    if mime_type in _VEGA_LITE_TYPES or file_name.lower().endswith(".vl.json"):
        return {
            "description": file_name,
            "id": common["id"],
            "specArtifactId": artifact_id,
            "specType": "vega-lite",
            "specVersion": "6",
            "state": "ready",
            "title": file_name.removesuffix(".vl.json"),
            "type": "chart",
        }
    return {**common, "name": file_name, "type": "file"}
