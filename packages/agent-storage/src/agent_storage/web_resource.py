"""Durable storage for fetched web resources.

Owns the SQLite index (``web_resource``, ``web_chunk``, ``web_chunk_fts``) and
the on-disk clean/raw payloads under ``<cache_root>/<resource_id>/``. Dedups by
content hash, supports TTL/stale checks, and exposes FTS5 search for
``web.find``. This store is a derived, deletable evidence cache — it never
becomes Session/Task/Memory authority (see WEB-PIPE-CON-01 §5.4).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from agent_core.domain.web_resource import (
    WebChunkView,
    WebRankedChunkView,
    WebResourceId,
    WebResourceStorePort,
    WebResourceView,
)

from agent_storage.database import SQLiteDatabase
from agent_storage.web_chunker import StoredWebChunk


class ResourceStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class StoredWebResource:
    resource_id: str
    requested_url: str
    final_url: str
    content_sha256: str
    created_at: str
    fetch_mode: str
    resource_status: ResourceStatus
    wire_bytes: int
    decoded_bytes: int
    clean_chars: int
    canonical_url: str | None = None
    title: str | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    expires_at: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RankedChunk:
    chunk: StoredWebChunk
    rank: float


class SQLiteWebResourceStore:
    def __init__(self, database_path: str | Path, cache_root: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._cache_root = Path(cache_root)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save(
        self,
        *,
        resource: StoredWebResource,
        chunks: tuple[StoredWebChunk, ...],
        clean_text: str,
        raw_html: str | None = None,
    ) -> WebResourceId:
        """Persist resource + chunks + payloads. Dedups by content hash and
        returns the canonical resource id (existing if a duplicate is found)."""
        existing = self.find_by_content_hash(resource.content_sha256)
        if existing is not None:
            return existing
        resource_id = WebResourceId.parse(resource.resource_id)
        self._write_payloads(resource_id, clean_text, raw_html)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO web_resource (
                    resource_id, requested_url, final_url, canonical_url,
                    title, content_type, fetch_mode, resource_status,
                    wire_bytes, decoded_bytes, clean_chars, content_sha256,
                    etag, last_modified, created_at, expires_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _resource_row(resource),
            )
            self._insert_chunks(connection, resource_id.value, chunks)
        return resource_id

    def get(self, resource_id: WebResourceId) -> StoredWebResource | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM web_resource WHERE resource_id = ?",
                (resource_id.value,),
            ).fetchone()
        return _resource_from_row(row) if row is not None else None

    def chunks(self, resource_id: WebResourceId) -> tuple[StoredWebChunk, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT ordinal, heading_path, char_start, char_end, token_count, text
                FROM web_chunk WHERE resource_id = ? ORDER BY ordinal
                """,
                (resource_id.value,),
            ).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)

    def find_by_content_hash(self, content_sha256: str) -> WebResourceId | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT resource_id FROM web_resource WHERE content_sha256 = ?",
                (content_sha256,),
            ).fetchone()
        return WebResourceId.parse(row["resource_id"]) if row is not None else None

    def clean_text(self, resource_id: WebResourceId) -> str:
        path = self._clean_path(resource_id)
        if not path.exists():
            raise FileNotFoundError(f"clean payload missing for {resource_id}")
        return path.read_text(encoding="utf-8")

    def is_stale(self, resource_id: WebResourceId, *, now: datetime) -> bool:
        resource = self.get(resource_id)
        if resource is None or resource.expires_at is None:
            return False
        try:
            expires = datetime.fromisoformat(resource.expires_at)
        except ValueError:
            return False
        return now >= expires

    def search(
        self,
        resource_id: WebResourceId,
        query: str,
        *,
        top_k: int = 12,
    ) -> tuple[RankedChunk, ...]:
        """FTS5 BM25 search within one resource's chunks."""
        if top_k <= 0:
            return ()
        match_query = _fts_match(query)
        if not match_query:
            return ()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT ordinal, bm25(web_chunk_fts) AS rank
                FROM web_chunk_fts
                WHERE resource_id = ? AND web_chunk_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (resource_id.value, match_query, top_k),
            ).fetchall()
        if not rows:
            return ()
        by_ordinal = {chunk.ordinal: chunk for chunk in self.chunks(resource_id)}
        ranked: list[RankedChunk] = []
        for row in rows:
            chunk = by_ordinal.get(row["ordinal"])
            if chunk is not None:
                ranked.append(RankedChunk(chunk=chunk, rank=float(row["rank"])))
        return tuple(ranked)

    def _clean_path(self, resource_id: WebResourceId) -> Path:
        return self._resource_dir(resource_id) / "clean.md"

    def _resource_dir(self, resource_id: WebResourceId) -> Path:
        return self._cache_root / resource_id.value

    def _write_payloads(
        self,
        resource_id: WebResourceId,
        clean_text: str,
        raw_html: str | None,
    ) -> None:
        directory = self._resource_dir(resource_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "clean.md").write_text(clean_text, encoding="utf-8")
        if raw_html is not None:
            (directory / "raw.html").write_text(raw_html, encoding="utf-8")

    def _insert_chunks(
        self,
        connection: sqlite3.Connection,
        resource_id: str,
        chunks: tuple[StoredWebChunk, ...],
    ) -> None:
        for chunk in chunks:
            connection.execute(
                """
                INSERT INTO web_chunk (
                    resource_id, ordinal, heading_path, char_start,
                    char_end, token_count, text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource_id,
                    chunk.ordinal,
                    chunk.heading_path,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.token_count,
                    chunk.text,
                ),
            )
            connection.execute(
                """
                INSERT INTO web_chunk_fts (resource_id, ordinal, heading_path, text)
                VALUES (?, ?, ?, ?)
                """,
                (
                    resource_id,
                    chunk.ordinal,
                    chunk.heading_path or "",
                    chunk.text,
                ),
            )

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS web_resource (
                    resource_id TEXT PRIMARY KEY,
                    requested_url TEXT NOT NULL,
                    final_url TEXT NOT NULL,
                    canonical_url TEXT,
                    title TEXT,
                    content_type TEXT,
                    fetch_mode TEXT NOT NULL,
                    resource_status TEXT NOT NULL,
                    wire_bytes INTEGER NOT NULL,
                    decoded_bytes INTEGER NOT NULL,
                    clean_chars INTEGER NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    etag TEXT,
                    last_modified TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_resource_sha256
                ON web_resource(content_sha256)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS web_chunk (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    heading_path TEXT,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    FOREIGN KEY(resource_id) REFERENCES web_resource(resource_id)
                )
                """
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS web_chunk_fts USING fts5(
                    resource_id UNINDEXED,
                    ordinal UNINDEXED,
                    heading_path,
                    text
                )
                """
            )


def _resource_row(resource: StoredWebResource) -> tuple[object, ...]:
    return (
        resource.resource_id,
        resource.requested_url,
        resource.final_url,
        resource.canonical_url,
        resource.title,
        resource.content_type,
        resource.fetch_mode,
        resource.resource_status.value,
        resource.wire_bytes,
        resource.decoded_bytes,
        resource.clean_chars,
        resource.content_sha256,
        resource.etag,
        resource.last_modified,
        resource.created_at,
        resource.expires_at,
        json.dumps(resource.metadata, sort_keys=True, separators=(",", ":")),
    )


def _resource_from_row(row: sqlite3.Row) -> StoredWebResource:
    metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    return StoredWebResource(
        resource_id=row["resource_id"],
        requested_url=row["requested_url"],
        final_url=row["final_url"],
        canonical_url=row["canonical_url"],
        title=row["title"],
        content_type=row["content_type"],
        fetch_mode=row["fetch_mode"],
        resource_status=ResourceStatus(row["resource_status"]),
        wire_bytes=row["wire_bytes"],
        decoded_bytes=row["decoded_bytes"],
        clean_chars=row["clean_chars"],
        content_sha256=row["content_sha256"],
        etag=row["etag"],
        last_modified=row["last_modified"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        metadata=metadata,
    )


def _chunk_from_row(row: sqlite3.Row) -> StoredWebChunk:
    return StoredWebChunk(
        ordinal=row["ordinal"],
        heading_path=row["heading_path"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        token_count=row["token_count"],
        text=row["text"],
    )


def _fts_match(query: str) -> str:
    """Build a safe FTS5 MATCH expression: quote each whitespace token so
    punctuation/operators in user input cannot break or broaden the query."""
    terms = [f'"{piece}"' for piece in query.split() if piece]
    return " ".join(terms)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class WebResourceStoreAdapter(WebResourceStorePort):
    """Adapt ``SQLiteWebResourceStore`` to the agent-core ``WebResourceStorePort``
    used by the projection/read/find tools, mapping persistence rows to the
    read-only view types."""

    def __init__(self, store: SQLiteWebResourceStore) -> None:
        self._store = store

    def get(self, resource_id: WebResourceId) -> WebResourceView | None:
        record = self._store.get(resource_id)
        if record is None:
            return None
        return WebResourceView(
            resource_id=record.resource_id,
            final_url=record.final_url,
            resource_status=record.resource_status.value,
            clean_chars=record.clean_chars,
            title=record.title,
            canonical_url=record.canonical_url,
        )

    def chunks(self, resource_id: WebResourceId) -> tuple[WebChunkView, ...]:
        return tuple(_chunk_view(chunk) for chunk in self._store.chunks(resource_id))

    def clean_text(self, resource_id: WebResourceId) -> str:
        return self._store.clean_text(resource_id)

    def search(
        self, resource_id: WebResourceId, query: str, *, top_k: int = 12
    ) -> tuple[WebRankedChunkView, ...]:
        return tuple(
            WebRankedChunkView(chunk=_chunk_view(ranked.chunk), rank=ranked.rank)
            for ranked in self._store.search(resource_id, query, top_k=top_k)
        )


def _chunk_view(chunk: StoredWebChunk) -> WebChunkView:
    return WebChunkView(
        ordinal=chunk.ordinal,
        heading_path=chunk.heading_path,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        token_count=chunk.token_count,
        text=chunk.text,
    )


__all__ = [
    "RankedChunk",
    "ResourceStatus",
    "SQLiteWebResourceStore",
    "StoredWebResource",
    "WebResourceStoreAdapter",
    "utc_now_iso",
]
