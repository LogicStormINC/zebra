from __future__ import annotations

import re
import sqlite3

from agent_core.domain.memories import MemoryRecord

MEMORY_COLUMNS = """
    memory.memory_id,
    memory.memory_type,
    memory.text,
    memory.confidence,
    memory.status,
    memory.visibility,
    memory.tenant_id,
    memory.user_id,
    memory.repo_id,
    memory.source_session_id,
    memory.source_event_start,
    memory.source_event_end,
    memory.source_commit_sha,
    memory.superseded_by,
    memory.expires_at,
    memory.created_at,
    memory.updated_at
"""


def initialize_memory_search(connection: sqlite3.Connection) -> None:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_records_fts
            USING fts5(memory_id UNINDEXED, text, tokenize='unicode61')
            """
        )
        connection.execute(
            """
            INSERT INTO memory_records_fts(memory_id, text)
            SELECT memory_id, text FROM memory_records
            WHERE memory_id NOT IN (SELECT memory_id FROM memory_records_fts)
            """
        )
    except sqlite3.OperationalError:
        pass


def sync_memory_search(connection: sqlite3.Connection, record: MemoryRecord) -> None:
    try:
        connection.execute(
            "DELETE FROM memory_records_fts WHERE memory_id = ?",
            (str(record.memory_id),),
        )
        connection.execute(
            "INSERT INTO memory_records_fts(memory_id, text) VALUES (?, ?)",
            (str(record.memory_id), record.text),
        )
    except sqlite3.OperationalError:
        pass


def fts_query(text: str) -> str:
    tokens = _query_tokens(text)
    return " OR ".join(f'"{token}"' for token in tokens)


def append_text_fallback(
    clauses: list[str],
    parameters: list[object],
    text: str,
) -> None:
    tokens = _query_tokens(text)
    if not tokens:
        return
    clauses.append("(" + " OR ".join("lower(memory.text) LIKE ?" for _ in tokens) + ")")
    parameters.extend(f"%{token}%" for token in tokens)


def _query_tokens(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"\w+", text.casefold())))[:16]
