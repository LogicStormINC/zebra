from __future__ import annotations

import builtins
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.ports.memory_store import MemoryStorePort

from agent_storage.database import SQLiteDatabase
from agent_storage.memory_search import (
    MEMORY_COLUMNS,
    append_text_fallback,
    fts_query,
    initialize_memory_search,
    sync_memory_search,
)


class SQLiteMemoryStore(MemoryStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_records (
                    memory_id,
                    memory_type,
                    text,
                    confidence,
                    status,
                    visibility,
                    tenant_id,
                    user_id,
                    repo_id,
                    source_session_id,
                    source_event_start,
                    source_event_end,
                    source_commit_sha,
                    superseded_by,
                    expires_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    memory_type = excluded.memory_type,
                    text = excluded.text,
                    confidence = excluded.confidence,
                    status = excluded.status,
                    visibility = excluded.visibility,
                    tenant_id = excluded.tenant_id,
                    user_id = excluded.user_id,
                    repo_id = excluded.repo_id,
                    source_session_id = excluded.source_session_id,
                    source_event_start = excluded.source_event_start,
                    source_event_end = excluded.source_event_end,
                    source_commit_sha = excluded.source_commit_sha,
                    superseded_by = excluded.superseded_by,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    str(record.memory_id),
                    record.memory_type.value,
                    record.text,
                    record.confidence,
                    record.status.value,
                    record.visibility.value,
                    record.tenant_id,
                    record.user_id,
                    record.repo_id,
                    None if record.source_session_id is None else str(record.source_session_id),
                    record.source_event_start,
                    record.source_event_end,
                    record.source_commit_sha,
                    None if record.superseded_by is None else str(record.superseded_by),
                    None if record.expires_at is None else record.expires_at.isoformat(),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
            sync_memory_search(connection, record)
        return record

    def get(self, memory_id: MemoryId) -> MemoryRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    memory_id,
                    memory_type,
                    text,
                    confidence,
                    status,
                    visibility,
                    tenant_id,
                    user_id,
                    repo_id,
                    source_session_id,
                    source_event_start,
                    source_event_end,
                    source_commit_sha,
                    superseded_by,
                    expires_at,
                    created_at,
                    updated_at
                FROM memory_records
                WHERE memory_id = ?
                """,
                (str(memory_id),),
            ).fetchone()
        if row is None:
            return None
        return _memory_record_from_row(row)

    def list(self, query: MemoryQuery) -> list[MemoryRecord]:
        clauses = ["1 = 1"]
        parameters: list[object] = []
        if query.tenant_id is not None:
            clauses.append("memory.tenant_id = ?")
            parameters.append(query.tenant_id)
        if query.user_id is not None:
            clauses.append("memory.user_id = ?")
            parameters.append(query.user_id)
        if query.repo_id is not None:
            clauses.append("memory.repo_id = ?")
            parameters.append(query.repo_id)
        if query.source_session_id is not None:
            clauses.append("memory.source_session_id = ?")
            parameters.append(str(query.source_session_id))
        if query.visibility is not None:
            clauses.append("memory.visibility = ?")
            parameters.append(query.visibility.value)
        if query.memory_types:
            clauses.append(f"memory.memory_type IN ({', '.join('?' for _ in query.memory_types)})")
            parameters.extend(memory_type.value for memory_type in query.memory_types)
        if query.statuses:
            clauses.append(f"memory.status IN ({', '.join('?' for _ in query.statuses)})")
            parameters.extend(status.value for status in query.statuses)
        if query.text_query is not None:
            try:
                return self._list_fts(query, clauses, parameters)
            except sqlite3.OperationalError:
                append_text_fallback(clauses, parameters, query.text_query)
        return self._list_rows(clauses, parameters, limit=query.limit)

    def _list_fts(
        self,
        query: MemoryQuery,
        clauses: Sequence[str],
        parameters: Sequence[object],
    ) -> builtins.list[MemoryRecord]:
        match_query = fts_query(query.text_query or "")
        if not match_query:
            return self._list_rows(clauses, parameters, limit=query.limit)
        fts_clauses = [*clauses, "memory_records_fts MATCH ?"]
        fts_parameters = [*parameters, match_query, query.limit]
        sql = f"""
            SELECT
                {MEMORY_COLUMNS}
            FROM memory_records AS memory
            JOIN memory_records_fts ON memory_records_fts.memory_id = memory.memory_id
            WHERE {" AND ".join(fts_clauses)}
            ORDER BY bm25(memory_records_fts), memory.updated_at DESC,
                     memory.created_at DESC, memory.memory_id ASC
            LIMIT ?
        """
        with self._database.connect() as connection:
            rows = connection.execute(sql, fts_parameters).fetchall()
        return [_memory_record_from_row(row) for row in rows]

    def _list_rows(
        self,
        clauses: Sequence[str],
        parameters: Sequence[object],
        *,
        limit: int,
    ) -> builtins.list[MemoryRecord]:
        sql = f"""
            SELECT {MEMORY_COLUMNS}
            FROM memory_records AS memory
            WHERE {" AND ".join(clauses)}
            ORDER BY memory.updated_at DESC, memory.created_at DESC, memory.memory_id ASC
            LIMIT ?
        """
        with self._database.connect() as connection:
            rows = connection.execute(sql, [*parameters, limit]).fetchall()
        return [_memory_record_from_row(row) for row in rows]

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    tenant_id TEXT,
                    user_id TEXT,
                    repo_id TEXT,
                    source_session_id TEXT,
                    source_event_start INTEGER,
                    source_event_end INTEGER,
                    source_commit_sha TEXT,
                    superseded_by TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_repo_scope
                ON memory_records(repo_id, status, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_repo_session_scope
                ON memory_records(repo_id, source_session_id, status, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_user_scope
                ON memory_records(user_id, status, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_tenant_scope
                ON memory_records(tenant_id, status, updated_at DESC)
                """
            )
            initialize_memory_search(connection)


def _memory_record_from_row(row: sqlite3.Row) -> MemoryRecord:
    memory_row = dict(row)
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_row["memory_id"])),
        memory_type=MemoryType(memory_row["memory_type"]),
        text=memory_row["text"],
        confidence=memory_row["confidence"],
        status=MemoryStatus(memory_row["status"]),
        visibility=MemoryVisibility(memory_row["visibility"]),
        tenant_id=memory_row["tenant_id"],
        user_id=memory_row["user_id"],
        repo_id=memory_row["repo_id"],
        source_session_id=(
            None
            if memory_row["source_session_id"] is None
            else SessionId(UUID(memory_row["source_session_id"]))
        ),
        source_event_start=memory_row["source_event_start"],
        source_event_end=memory_row["source_event_end"],
        source_commit_sha=memory_row["source_commit_sha"],
        superseded_by=(
            None
            if memory_row["superseded_by"] is None
            else MemoryId(UUID(memory_row["superseded_by"]))
        ),
        expires_at=_parse_datetime(memory_row["expires_at"]),
        created_at=datetime.fromisoformat(memory_row["created_at"]),
        updated_at=datetime.fromisoformat(memory_row["updated_at"]),
    )


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value))
