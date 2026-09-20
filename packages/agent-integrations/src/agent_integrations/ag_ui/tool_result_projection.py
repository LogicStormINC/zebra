"""Safe AG-UI payloads for ordinary tool results and published user files."""

import json
from collections.abc import Mapping
from typing import Any

from agent_integrations.ag_ui.contracts import AgUiProjectionError


def tool_result_content(payload: Mapping[str, Any], output: str) -> str:
    metadata = payload.get("metadata")
    status = payload.get("status")
    safe_status = status if isinstance(status, str) and status else "unknown"
    if not isinstance(metadata, Mapping) or metadata.get("delivery") is not True:
        safe_metadata = {
            key: value
            for key in ("reason", "detail", "retryable", "recoverable", "http_status")
            if _safe_value(value := (metadata or {}).get(key))
        }
        return _json_text(
            {
                "metadata": safe_metadata,
                "output": output,
                "status": safe_status,
                "type": "zebra.tool_result.v1",
            }
        )
    artifact_uri = metadata.get("artifact_uri")
    file_name = metadata.get("file_name")
    mime_type = metadata.get("mime_type")
    size_bytes = metadata.get("size_bytes")
    if not (
        isinstance(artifact_uri, str)
        and artifact_uri.startswith("artifact://")
        and isinstance(file_name, str)
        and file_name
        and isinstance(mime_type, str)
        and mime_type
        and isinstance(size_bytes, int)
        and size_bytes >= 0
        and isinstance(status, str)
        and status
    ):
        return output
    return _json_text(
        {
            "artifact": {
                "file_name": file_name,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "uri": artifact_uri,
            },
            "output": output,
            "status": status,
            "type": "zebra.user_file.v1",
        }
    )


def _json_text(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise AgUiProjectionError("tool result is not JSON serializable") from exc


def _safe_value(value: object) -> bool:
    return isinstance(value, bool | int | float) or (
        isinstance(value, str) and bool(value.strip()) and len(value) <= 2_048
    )
