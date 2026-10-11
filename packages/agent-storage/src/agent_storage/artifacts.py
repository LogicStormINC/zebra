from __future__ import annotations

import re
import sqlite3
from asyncio import CancelledError
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import TypedDict, overload
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.model_call_store import ModelCallStorePort
from agent_core.ports.session_artifact_read import (
    MAX_ARTIFACT_PROJECTION_BYTES,
    PreviewState,
    SessionArtifact,
    SessionArtifactReadPort,
    SessionArtifactReadUnavailableError,
    parse_session_artifact_id,
)
from agent_core.ports.tool_run_store import ToolRunStorePort

from agent_storage.database import SQLiteDatabase
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
        self._database: SQLiteDatabase | None = None
        if isinstance(database_path, str | Path):
            if tool_runs is not None:
                raise TypeError("tool_runs cannot be supplied with a database path")
            self._model_calls = SQLiteModelCallStore(database_path)
            self._tool_runs = SQLiteToolRunStore(database_path)
            self._database = SQLiteDatabase(database_path)
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

    def get_for_session(self, session_id: SessionId, artifact_id: str) -> SessionArtifact | None:
        from agent_storage.artifact_object_reads import artifact_read_scope

        key = parse_session_artifact_id(artifact_id)
        if key is None:
            return None
        if self._database is None:
            # ponytail: injected list-only stores cannot provide a bounded point read.
            raise SessionArtifactReadUnavailableError("Artifact point source is not configured")
        source, sequence = ("tool-run", None) if isinstance(key, UUID) else key
        record_type = ModelCallRecord if source == "model-call" else ToolRunRecord
        table = "model_calls" if source == "model-call" else "tool_runs"
        where = "session_id = ? AND " + ("artifact_uri = ?" if sequence is None else "sequence = ?")
        parameters = (str(session_id), f"artifact://{key}" if sequence is None else sequence)
        fields = tuple(record_type.model_fields)
        text_fields = _MODEL_TEXT_FIELDS if source == "model-call" else _TOOL_TEXT_FIELDS
        # Read scalar byte sizes first, in the same snapshot as the selected body.
        size = "512 + " + " + ".join(
            f"coalesce(length(cast({field} AS BLOB)), 0)" for field in text_fields
        )
        with artifact_read_scope() as scope, closing(self._database.connect()) as connection:
            connection.execute(f"PRAGMA busy_timeout = {max(1, int(scope.remaining() * 1000))}")

            def interrupted() -> int:
                try:
                    scope.remaining()
                except (CancelledError, TimeoutError):
                    return 1
                return 0

            connection.set_progress_handler(interrupted, 100)
            try:
                connection.execute("BEGIN")
                row = connection.execute(
                    f"SELECT sequence, {size} AS record_bytes FROM {table} WHERE {where} "
                    "ORDER BY sequence LIMIT 1",
                    parameters,
                ).fetchone()
                scope.remaining()
                if row is None:
                    return None
                if row["record_bytes"] > MAX_ARTIFACT_PROJECTION_BYTES:
                    raise SessionArtifactReadUnavailableError(
                        "Artifact projection exceeds its byte bound"
                    )
                record = connection.execute(
                    f"SELECT {', '.join(fields)} FROM {table} "
                    "WHERE session_id = ? AND sequence = ?",
                    (str(session_id), row["sequence"]),
                ).fetchone()
            except sqlite3.OperationalError:
                scope.remaining()  # Preserve a proven deadline/cancellation, not "interrupted".
                raise
            scope.remaining()
            assert record is not None  # The read transaction pins both SELECTs.
            validated = record_type.model_validate(dict(record))
            return (
                _model_artifact(validated)
                if isinstance(validated, ModelCallRecord)
                else _tool_artifact(validated)
            )


_MODEL_TEXT_FIELDS = ("session_id", "provider", "model_name", "assistant_message", "created_at")
_TOOL_TEXT_FIELDS = (
    "session_id",
    "tool_name",
    "status",
    "idempotency_key",
    "output",
    "artifact_uri",
    "created_at",
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
