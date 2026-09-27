"""Project published Artifact metadata into replayable rich-content parts."""

from collections.abc import Mapping
from typing import Any

from ag_ui.core import CustomEvent

_INLINE_IMAGE_TYPES = frozenset(
    {"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"}
)
_INLINE_VIDEO_TYPES = frozenset({"video/mp4", "video/ogg", "video/webm"})
_VEGA_LITE_TYPES = frozenset(
    {"application/vnd.vegalite+json", "application/vnd.vegalite.v6+json"}
)


def project_content_part(
    payload: Mapping[str, Any],
    *,
    tool_call_id: str,
    timestamp: int,
) -> CustomEvent | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("delivery") is not True:
        return None
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
    part = _part_for_artifact(
        artifact_id=artifact_id,
        file_name=file_name.strip(),
        mime_type=mime_type.strip().lower(),
        size_bytes=size_bytes,
        tool_call_id=tool_call_id,
    )
    return CustomEvent(
        timestamp=timestamp,
        name="zebra.content_part",
        value={"part": part, "schema_version": "1", "tool_call_id": tool_call_id},
    )


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
