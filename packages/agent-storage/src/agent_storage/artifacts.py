from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict, overload

from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.model_call_store import ModelCallStorePort
from agent_core.ports.session_artifact_read import (
    PreviewState,
    SessionArtifact,
    SessionArtifactReadPort,
)
from agent_core.ports.tool_run_store import ToolRunStorePort

from agent_storage.model_calls import SQLiteModelCallStore
from agent_storage.tool_runs import SQLiteToolRunStore


class SanitizedPreview(TypedDict):
    preview: str
    state: PreviewState


class SQLiteArtifactStore(SessionArtifactReadPort):
    @overload
    def __init__(self, database_path: str | Path) -> None: ...

    @overload
    def __init__(
        self,
        database_path: ModelCallStorePort,
        tool_runs: ToolRunStorePort,
    ) -> None: ...

    def __init__(
        self,
        database_path: ModelCallStorePort | str | Path,
        tool_runs: ToolRunStorePort | None = None,
    ) -> None:
        self._model_calls: ModelCallStorePort
        self._tool_runs: ToolRunStorePort
        if isinstance(database_path, str | Path):
            if tool_runs is not None:
                raise TypeError("tool_runs cannot be supplied with a database path")
            self._model_calls = SQLiteModelCallStore(database_path)
            self._tool_runs = SQLiteToolRunStore(database_path)
            return
        if tool_runs is None:
            raise TypeError("tool_runs is required with an injected model-call store")
        self._model_calls = database_path
        self._tool_runs = tool_runs

    def list_for_session(self, session_id: SessionId) -> list[SessionArtifact]:
        return compose_session_artifacts(
            self._model_calls.list_for_session(session_id),
            self._tool_runs.list_for_session(session_id),
        )


def compose_session_artifacts(
    model_calls: Iterable[ModelCallRecord],
    tool_runs: Iterable[ToolRunRecord],
) -> list[SessionArtifact]:
    """Compose replayable Model/Tool projections into the shared Artifact view."""
    artifacts = [_model_artifact(record) for record in model_calls]
    artifacts.extend(_tool_artifact(record) for record in tool_runs)
    return sorted(artifacts, key=lambda artifact: (artifact.sequence, artifact.source))


def _model_artifact(record: ModelCallRecord) -> SessionArtifact:
    sanitized = _sanitize_preview(record.assistant_message)
    return SessionArtifact(
        artifact_id=f"model-call:{record.sequence}",
        session_id=record.session_id,
        sequence=record.sequence,
        source="model_call",
        kind="assistant_message",
        label=record.model_name or record.provider or "model response",
        uri=None,
        preview=sanitized["preview"],
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


def _tool_artifact(record: ToolRunRecord) -> SessionArtifact:
    sanitized = _sanitize_preview(record.output)
    return SessionArtifact(
        artifact_id=f"tool-run:{record.sequence}",
        session_id=record.session_id,
        sequence=record.sequence,
        source="tool_run",
        kind="tool_output",
        label=record.tool_name,
        uri=record.artifact_uri,
        preview=sanitized["preview"],
        preview_state=sanitized["state"],
        metadata={
            "tool_name": record.tool_name,
            "status": record.status,
            "idempotency_key": record.idempotency_key,
            "created_at": record.created_at.isoformat(),
        },
    )


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
