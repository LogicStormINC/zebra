from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from agent_core.domain.identifiers import SessionId

from agent_storage.model_calls import SQLiteModelCallStore
from agent_storage.tool_runs import SQLiteToolRunStore


class PreviewState(TypedDict):
    redacted: bool
    truncated: bool


class SanitizedPreview(TypedDict):
    preview: str
    state: PreviewState


@dataclass(frozen=True)
class SessionArtifact:
    artifact_id: str
    session_id: SessionId
    sequence: int
    source: str
    kind: str
    label: str
    uri: str | None
    preview: str
    preview_state: PreviewState
    metadata: dict[str, object]


class SQLiteArtifactStore:
    def __init__(self, database_path: str | Path) -> None:
        self._model_calls = SQLiteModelCallStore(database_path)
        self._tool_runs = SQLiteToolRunStore(database_path)

    def list_for_session(self, session_id: SessionId) -> list[SessionArtifact]:
        artifacts = [
            SessionArtifact(
                artifact_id=f"model-call:{record.sequence}",
                session_id=record.session_id,
                sequence=record.sequence,
                source="model_call",
                kind="assistant_message",
                label=record.model_name or record.provider or "model response",
                uri=None,
                preview=(sanitized := _sanitize_preview(record.assistant_message))["preview"],
                preview_state=sanitized["state"],
                metadata={
                    "provider": record.provider,
                    "model_name": record.model_name,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "total_tokens": record.total_tokens,
                    "latency_ms": record.latency_ms,
                    "cache_hit": record.cache_hit,
                    "cost_usd": record.cost_usd,
                    "tool_call_count": record.tool_call_count,
                    "created_at": record.created_at.isoformat(),
                },
            )
            for record in self._model_calls.list_for_session(session_id)
        ]
        artifacts.extend(
            SessionArtifact(
                artifact_id=f"tool-run:{record.sequence}",
                session_id=record.session_id,
                sequence=record.sequence,
                source="tool_run",
                kind="tool_output",
                label=record.tool_name,
                uri=record.artifact_uri,
                preview=(sanitized := _sanitize_preview(record.output))["preview"],
                preview_state=sanitized["state"],
                metadata={
                    "tool_name": record.tool_name,
                    "status": record.status,
                    "idempotency_key": record.idempotency_key,
                    "created_at": record.created_at.isoformat(),
                },
            )
            for record in self._tool_runs.list_for_session(session_id)
        )
        return sorted(artifacts, key=lambda artifact: (artifact.sequence, artifact.source))


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{10,}"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(token\s*[:=]\s*)(\S+)"),
)
_REDACTED = "[REDACTED]"
_PREVIEW_LIMIT = 160


def _sanitize_preview(value: str) -> SanitizedPreview:
    sanitized = value
    redacted = False
    for pattern in _SECRET_PATTERNS:
        replaced, count = pattern.subn(
            lambda match: match.group(1) + _REDACTED if match.lastindex else _REDACTED,
            sanitized,
        )
        if count:
            redacted = True
            sanitized = replaced
    truncated = len(sanitized) > _PREVIEW_LIMIT
    if truncated:
        sanitized = sanitized[:_PREVIEW_LIMIT] + "..."
    return {
        "preview": sanitized,
        "state": {
            "redacted": redacted,
            "truncated": truncated,
        },
    }
