"""Governed Memory PostgreSQL row mapping and bounded query construction."""

import hashlib
import json
from datetime import datetime
from typing import Any, cast

from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    GovernedMemoryTombstone,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)


def provenance_digest(record: MemoryRecord) -> str:
    payload = {
        "memory_id": str(record.memory_id),
        "memory_type": record.memory_type.value,
        "visibility": record.visibility.value,
        "tenant_id": record.tenant_id,
        "user_id": record.user_id,
        "repo_id": record.repo_id,
        "source_session_id": None
        if record.source_session_id is None
        else str(record.source_session_id),
        "source_event_start": record.source_event_start,
        "source_event_end": record.source_event_end,
        "source_commit_sha": record.source_commit_sha,
        "created_at": record.created_at.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def memory_values(namespace: str, entry: GovernedMemoryEntry) -> tuple[object, ...]:
    record = entry.record
    return (
        namespace,
        record.memory_id,
        entry.revision,
        record.memory_type.value,
        record.text,
        record.confidence,
        record.status.value,
        record.visibility.value,
        record.tenant_id,
        record.user_id,
        record.repo_id,
        record.source_session_id,
        record.source_event_start,
        record.source_event_end,
        record.source_commit_sha,
        record.superseded_by,
        record.expires_at,
        record.created_at,
        record.updated_at,
        entry.creation_key,
        entry.content_digest,
        provenance_digest(record),
    )


def authority_from_row(row: dict[str, Any]) -> GovernedMemoryEntry | GovernedMemoryTombstone:
    if row["status"] == MemoryStatus.DELETED.value:
        return GovernedMemoryTombstone(
            deployment_namespace=row["deployment_namespace"],
            memory_id=MemoryId(row["memory_id"]),
            revision=row["revision"],
            memory_type=MemoryType(row["memory_type"]),
            visibility=MemoryVisibility(row["visibility"]),
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            repo_id=row["repo_id"],
            provenance_digest=row["provenance_digest"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    record = record_from_row(row)
    return GovernedMemoryEntry(
        deployment_namespace=row["deployment_namespace"],
        record=record,
        revision=row["revision"],
        creation_key=row["creation_key"],
        content_digest=row["content_digest"],
    )


def record_from_row(row: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(row["memory_id"]),
        memory_type=MemoryType(row["memory_type"]),
        text=row["text"],
        confidence=row["confidence"],
        status=MemoryStatus(row["status"]),
        visibility=MemoryVisibility(row["visibility"]),
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        repo_id=row["repo_id"],
        source_session_id=(
            None if row["source_session_id"] is None else SessionId(row["source_session_id"])
        ),
        source_event_start=row["source_event_start"],
        source_event_end=row["source_event_end"],
        source_commit_sha=row["source_commit_sha"],
        superseded_by=(None if row["superseded_by"] is None else MemoryId(row["superseded_by"])),
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def query_records(connection: Any, namespace: str, query: MemoryQuery) -> list[MemoryRecord]:
    return [record_from_row(row) for row in _query_rows(connection, namespace, query)]


def query_authority_entries(
    connection: Any,
    namespace: str,
    query: MemoryQuery,
    *,
    as_of: datetime,
) -> list[GovernedMemoryEntry]:
    """Read confirmed, currently eligible authority rows in the caller's transaction."""

    rows = _query_rows(
        connection,
        namespace,
        query,
        extra_clauses=("(expires_at IS NULL OR expires_at > %s)",),
        extra_parameters=(as_of,),
    )
    entries: list[GovernedMemoryEntry] = []
    for row in rows:
        authority = authority_from_row(row)
        if isinstance(authority, GovernedMemoryEntry):
            entries.append(authority)
    return entries


def _query_rows(
    connection: Any,
    namespace: str,
    query: MemoryQuery,
    *,
    extra_clauses: tuple[str, ...] = (),
    extra_parameters: tuple[object, ...] = (),
) -> list[dict[str, Any]]:
    clauses = ["deployment_namespace = %s", "status != 'deleted'"]
    where_parameters: list[object] = [namespace]
    for column, value in (
        ("tenant_id", query.tenant_id),
        ("user_id", query.user_id),
        ("repo_id", query.repo_id),
        ("source_session_id", query.source_session_id),
    ):
        if value is not None:
            clauses.append(f"{column} = %s")
            where_parameters.append(value)
    if query.visibility is not None:
        clauses.append("visibility = %s")
        where_parameters.append(query.visibility.value)
    if query.memory_types:
        clauses.append("memory_type = ANY(%s)")
        where_parameters.append([item.value for item in query.memory_types])
    if query.statuses:
        clauses.append("status = ANY(%s)")
        where_parameters.append([item.value for item in query.statuses])
    clauses.extend(extra_clauses)
    where_parameters.extend(extra_parameters)
    rank = ""
    rank_parameters: list[object] = []
    order = "updated_at DESC, created_at DESC, memory_id ASC"
    if query.text_query is not None:
        clauses.append("search_vector @@ websearch_to_tsquery('simple', %s)")
        where_parameters.append(query.text_query)
        rank = ", ts_rank_cd(search_vector, websearch_to_tsquery('simple', %s)) AS rank"
        rank_parameters.append(query.text_query)
        order = "rank DESC, updated_at DESC, created_at DESC, memory_id ASC"
    rows = connection.execute(
        f"""
        SELECT * {rank} FROM governed_memory_records
        WHERE {" AND ".join(clauses)} ORDER BY {order} LIMIT %s
        """,
        [*rank_parameters, *where_parameters, query.limit],
    ).fetchall()
    return cast(list[dict[str, Any]], rows)
