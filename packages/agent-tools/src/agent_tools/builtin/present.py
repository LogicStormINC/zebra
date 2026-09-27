from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import (
    ArtifactPayloadReadInspection,
    ArtifactPayloadReadPort,
    ArtifactPayloadReadStatus,
)

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

_MAX_PARTS = 8
_IMAGE_TYPES = frozenset({"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"})
_VIDEO_TYPES = frozenset({"video/mp4", "video/ogg", "video/webm"})
_CHART_TYPES = frozenset(
    {"application/json", "application/vnd.vegalite+json", "application/vnd.vegalite.v6+json"}
)


class _ArtifactPresentationError(RuntimeError):
    """The Artifact exists but is not safe for the requested presentation type."""


content_present_contract = ToolContract(
    name="content.present",
    required_arguments=("parts",),
    description=(
        "Present existing current-session Artifacts inline in the answer. Use images only when "
        "they add evidence or clarity, charts for structured comparisons or trends, and video "
        "only when motion or sequence matters. Do not add decorative media."
    ),
    argument_properties={
        "parts": {
            "type": "array",
            "minItems": 1,
            "maxItems": _MAX_PARTS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "artifact_uri"],
                "properties": {
                    "type": {"type": "string", "enum": ["image", "video", "chart", "file"]},
                    "artifact_uri": {
                        "type": "string",
                        "description": "Current-session artifact:// URI.",
                    },
                    "alt": {
                        "type": "string",
                        "description": "Required concise image alternative text.",
                    },
                    "title": {"type": "string", "description": "Required for video and chart."},
                    "description": {"type": "string"},
                    "name": {"type": "string", "description": "Optional file download name."},
                    "width": {"type": "integer", "minimum": 1, "maximum": 16384},
                    "height": {"type": "integer", "minimum": 1, "maximum": 16384},
                    "duration_ms": {"type": "integer", "minimum": 0},
                    "thumbnail_artifact_uri": {"type": "string"},
                    "poster_artifact_uri": {"type": "string"},
                    "captions_artifact_uri": {"type": "string"},
                    "captions_language": {"type": "string"},
                    "transcript_artifact_uri": {"type": "string"},
                    "data_artifact_uri": {"type": "string"},
                    "fallback_image_artifact_uri": {"type": "string"},
                    "fallback_table_artifact_uri": {"type": "string"},
                },
            },
        }
    },
)


class ContentPresentTool:
    def __init__(self, reader: ArtifactPayloadReadPort, session_id: SessionId) -> None:
        self._reader = reader
        self._session_id = session_id

    @property
    def contract(self) -> ToolContract:
        return content_present_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        raw_parts = tool_call.arguments.get("parts")
        if not isinstance(raw_parts, list) or not 1 <= len(raw_parts) <= _MAX_PARTS:
            raise ToolArgumentError(f"content.present parts must contain 1 to {_MAX_PARTS} items")
        try:
            parts = [
                self._build_part(item, index, str(tool_call.tool_call_id))
                for index, item in enumerate(raw_parts)
            ]
        except (FileNotFoundError, PermissionError, _ArtifactPresentationError) as exc:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={"reason": "artifact_unavailable", "detail": str(exc)[:1000]},
            )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"Presented {len(parts)} rich content part(s).",
            metadata={"content_parts": parts, "delivery": True, "schema_version": "2"},
        )

    def _build_part(self, value: object, index: int, tool_call_id: str) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise ToolArgumentError("content.present part must be an object")
        kind = _required_text(value, "type", maximum=16)
        uri = _required_text(value, "artifact_uri", maximum=128)
        inspection = self._artifact(uri)
        part_id = f"content:{tool_call_id}:{index}:{inspection.artifact_id}"
        if kind == "image":
            _require_mime(inspection, _IMAGE_TYPES, "image")
            return _compact(
                {
                    **_artifact_part(part_id, "image", inspection),
                    "alt": _required_text(value, "alt", maximum=500),
                    "thumbnailArtifactId": self._related(
                        value, "thumbnail_artifact_uri", _IMAGE_TYPES
                    ),
                    "width": _optional_int(value, "width", minimum=1, maximum=16_384),
                    "height": _optional_int(value, "height", minimum=1, maximum=16_384),
                }
            )
        if kind == "video":
            _require_mime(inspection, _VIDEO_TYPES, "video")
            return _compact(
                {
                    **_artifact_part(part_id, "video", inspection),
                    "title": _required_text(value, "title", maximum=500),
                    "description": _optional_text(value, "description", maximum=2000),
                    "posterArtifactId": self._related(value, "poster_artifact_uri", _IMAGE_TYPES),
                    "captionsArtifactId": self._related(
                        value, "captions_artifact_uri", frozenset({"text/vtt"})
                    ),
                    "captionsLanguage": _optional_text(value, "captions_language", maximum=32),
                    "transcriptArtifactId": self._related_prefix(
                        value, "transcript_artifact_uri", "text/"
                    ),
                    "durationMs": _optional_int(value, "duration_ms", minimum=0),
                    "width": _optional_int(value, "width", minimum=1, maximum=16_384),
                    "height": _optional_int(value, "height", minimum=1, maximum=16_384),
                }
            )
        if kind == "chart":
            if inspection.mime_type not in _CHART_TYPES and not (
                inspection.file_name or ""
            ).lower().endswith(".vl.json"):
                raise _ArtifactPresentationError(
                    "chart Artifact must contain a Vega-Lite JSON specification"
                )
            return _compact(
                {
                    "id": part_id,
                    "type": "chart",
                    "state": "ready",
                    "specType": "vega-lite",
                    "specVersion": "6",
                    "specArtifactId": str(inspection.artifact_id),
                    "dataArtifactId": self._related(
                        value, "data_artifact_uri", frozenset({"application/json", "text/csv"})
                    ),
                    "fallbackImageArtifactId": self._related(
                        value, "fallback_image_artifact_uri", _IMAGE_TYPES
                    ),
                    "fallbackTableArtifactId": self._related(
                        value,
                        "fallback_table_artifact_uri",
                        frozenset({"application/json", "text/csv"}),
                    ),
                    "title": _required_text(value, "title", maximum=500),
                    "description": _required_text(value, "description", maximum=2000),
                }
            )
        if kind == "file":
            name = _optional_text(value, "name", maximum=255) or inspection.file_name
            if not name:
                raise ToolArgumentError("content.present file requires name when metadata has none")
            return _compact(
                {
                    **_artifact_part(part_id, "file", inspection),
                    "name": name,
                    "description": _optional_text(value, "description", maximum=2000),
                }
            )
        raise ToolArgumentError("content.present type must be image, video, chart, or file")

    def _artifact(self, uri: str) -> ArtifactPayloadReadInspection:
        artifact_id = _artifact_id(uri)
        inspection = self._reader.describe_payload(self._session_id, uri)
        if inspection is None or inspection.status is not ArtifactPayloadReadStatus.AVAILABLE:
            raise FileNotFoundError(f"Artifact is not available in this session: {uri}")
        if inspection.session_id != self._session_id or inspection.artifact_id != artifact_id:
            raise PermissionError("Artifact authority does not match the current session")
        return inspection

    def _related(
        self, value: Mapping[object, object], key: str, allowed: frozenset[str]
    ) -> str | None:
        uri = _optional_text(value, key, maximum=128)
        if uri is None:
            return None
        inspection = self._artifact(uri)
        _require_mime(inspection, allowed, key)
        return str(inspection.artifact_id)

    def _related_prefix(self, value: Mapping[object, object], key: str, prefix: str) -> str | None:
        uri = _optional_text(value, key, maximum=128)
        if uri is None:
            return None
        inspection = self._artifact(uri)
        if not inspection.mime_type.startswith(prefix):
            raise _ArtifactPresentationError(f"{key} Artifact has unsupported MIME type")
        return str(inspection.artifact_id)


def _artifact_part(
    part_id: str, kind: str, inspection: ArtifactPayloadReadInspection
) -> dict[str, object]:
    return {
        "id": part_id,
        "type": kind,
        "state": "ready",
        "artifactId": str(inspection.artifact_id),
        "fileName": inspection.file_name,
        "mimeType": inspection.mime_type,
        "sizeBytes": inspection.size_bytes,
    }


def _artifact_id(uri: str) -> UUID:
    if not uri.startswith("artifact://") or any(char in uri for char in "?#"):
        raise ToolArgumentError("content.present requires a canonical artifact:// UUID")
    try:
        return UUID(uri.removeprefix("artifact://"))
    except ValueError as exc:
        raise ToolArgumentError("content.present requires a canonical artifact:// UUID") from exc


def _required_text(value: Mapping[object, object], key: str, *, maximum: int) -> str:
    result = _optional_text(value, key, maximum=maximum)
    if result is None:
        raise ToolArgumentError(f"content.present requires non-blank {key}")
    return result


def _optional_text(value: Mapping[object, object], key: str, *, maximum: int) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > maximum:
        raise ToolArgumentError(f"content.present {key} must be 1 to {maximum} characters")
    return raw.strip()


def _optional_int(
    value: Mapping[object, object], key: str, *, minimum: int, maximum: int | None = None
) -> int | None:
    raw = value.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
        raise ToolArgumentError(f"content.present {key} is outside the supported range")
    if maximum is not None and raw > maximum:
        raise ToolArgumentError(f"content.present {key} is outside the supported range")
    return raw


def _require_mime(
    inspection: ArtifactPayloadReadInspection, allowed: frozenset[str], label: str
) -> None:
    if inspection.mime_type not in allowed:
        raise _ArtifactPresentationError(f"{label} Artifact has unsupported MIME type")


def _compact(value: Mapping[str, object | None]) -> dict[str, object]:
    return {key: item for key, item in value.items() if item is not None}
