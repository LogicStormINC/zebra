from __future__ import annotations

import json
import sqlite3
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId

from agent_storage.session_handoff_rows import HandoffStorageConflictError


def persisted_task_model_id(
    connection: sqlite3.Connection,
    source_session_id: SessionId,
) -> str | None:
    lineage = connection.execute(
        "SELECT root_session_id FROM session_lineage WHERE session_id = ?",
        (str(source_session_id),),
    ).fetchone()
    root_session_id = source_session_id if lineage is None else SessionId(UUID(lineage[0]))
    rows = connection.execute(
        """
        SELECT payload FROM session_events
        WHERE event_type = ? AND session_id IN (
            SELECT session_id FROM session_lineage WHERE root_session_id = ?
            UNION SELECT ?
        )
        """,
        (EventType.TASK_PREPARED.value, str(root_session_id), str(root_session_id)),
    ).fetchall()
    selected: str | None = None
    for row in rows:
        payload = json.loads(row["payload"])
        model_id = payload.get("model_id") if isinstance(payload, dict) else None
        if model_id is None:
            continue
        if not isinstance(model_id, str) or not model_id.strip():
            raise HandoffStorageConflictError("task model selection is invalid")
        normalized = model_id.strip()
        if selected is not None and selected != normalized:
            raise HandoffStorageConflictError("task model selection drift detected")
        selected = normalized
    return selected
