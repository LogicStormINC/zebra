"""Fail-closed replay of governed SQLite Memory authority into PostgreSQL."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent_core.domain.governed_memories import (
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility

from agent_storage.postgres.governed_memory_rows import provenance_digest
from agent_storage.postgres.migration_snapshot import SnapshotRecord


class MemoryMigrationError(ValueError):
    """Raised when governed Memory cannot be imported without guessing."""


@dataclass(frozen=True, slots=True)
class MemoryReplayReport:
    record_count: int


_COLUMNS = {
    "memory_id",
    "memory_type",
    "text",
    "confidence",
    "status",
    "visibility",
    "tenant_id",
    "user_id",
    "repo_id",
    "source_session_id",
    "source_event_start",
    "source_event_end",
    "source_commit_sha",
    "superseded_by",
    "expires_at",
    "created_at",
    "updated_at",
}
_SINGLETON_TYPES = {
    MemoryType.PROJECT_RULE,
    MemoryType.PROCEDURE,
    MemoryType.ARCHITECTURE_FACT,
}


def replay_memory_snapshot(
    connection: Any,
    deployment_namespace: str,
    records_by_table: Mapping[str, Sequence[SnapshotRecord]],
) -> MemoryReplayReport:
    records = tuple(_parse(record) for record in records_by_table.get("memory_records", ()))
    _validate_source(records)
    _validate_event_bindings(connection, deployment_namespace, records)
    for record in records:
        values = _postgres_values(deployment_namespace, record)
        connection.execute(
            """INSERT INTO governed_memory_records (
                deployment_namespace, memory_id, revision, memory_type, text,
                confidence, status, visibility, tenant_id, user_id, repo_id,
                source_session_id, source_event_start, source_event_end,
                source_commit_sha, superseded_by, expires_at, created_at, updated_at,
                creation_key, content_digest, provenance_digest
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            values,
        )
    if records:
        connection.execute("REINDEX INDEX governed_memory_search")
    return MemoryReplayReport(record_count=len(records))


def _parse(record: SnapshotRecord) -> MemoryRecord:
    values = _record_values(record)
    try:
        return MemoryRecord.model_validate(values)
    except (TypeError, ValueError) as error:
        raise MemoryMigrationError("governed Memory record failed validation") from error


def _record_values(record: SnapshotRecord) -> dict[str, object]:
    if set(record.columns) != _COLUMNS or len(record.columns) != len(record.values):
        raise MemoryMigrationError(f"unexpected {record.table} column contract")
    return dict(zip(record.columns, record.values, strict=True))


def _validate_source(records: Sequence[MemoryRecord]) -> None:
    ids = [record.memory_id for record in records]
    if len(ids) != len(set(ids)):
        raise MemoryMigrationError("governed Memory identities are duplicated")
    creation_keys = [canonical_governed_memory_creation_key(record) for record in records]
    if len(creation_keys) != len(set(creation_keys)):
        raise MemoryMigrationError("governed Memory creation identities are duplicated")
    by_id = {record.memory_id: record for record in records}
    singleton_counts: Counter[tuple[str, str, MemoryType]] = Counter()
    for record in records:
        if record.created_at > record.updated_at:
            raise MemoryMigrationError("governed Memory timestamps are not ordered")
        if record.expires_at is not None and record.expires_at < record.created_at:
            raise MemoryMigrationError("governed Memory expiry predates creation")
        if record.status is MemoryStatus.SUPERSEDED:
            if record.superseded_by not in by_id:
                raise MemoryMigrationError("superseded Memory target is not in snapshot")
            if by_id[record.superseded_by].status is MemoryStatus.DELETED:
                raise MemoryMigrationError("superseded Memory target is deleted")
        if record.status is MemoryStatus.DELETED and record.superseded_by is not None:
            raise MemoryMigrationError("deleted Memory cannot retain a superseded target")
        if record.status is MemoryStatus.CONFIRMED and record.memory_type in _SINGLETON_TYPES:
            singleton_counts[
                (record.visibility.value, _scope_value(record), record.memory_type)
            ] += 1
    if any(count > 1 for count in singleton_counts.values()):
        raise MemoryMigrationError("confirmed governed Memory singleton is duplicated")


def _validate_event_bindings(
    connection: Any,
    deployment_namespace: str,
    records: Sequence[MemoryRecord],
) -> None:
    for record in records:
        if record.source_session_id is None:
            continue
        session = connection.execute(
            """SELECT 1 FROM session_streams
            WHERE deployment_namespace = %s AND session_id = %s""",
            (deployment_namespace, record.source_session_id),
        ).fetchone()
        if session is None:
            raise MemoryMigrationError("governed Memory source session is missing")
        if record.source_event_start is None:
            continue
        assert record.source_event_end is not None
        row = connection.execute(
            """SELECT count(*) AS count FROM session_events
            WHERE deployment_namespace = %s AND session_id = %s
              AND sequence BETWEEN %s AND %s""",
            (
                deployment_namespace,
                record.source_session_id,
                record.source_event_start,
                record.source_event_end,
            ),
        ).fetchone()
        expected = record.source_event_end - record.source_event_start + 1
        if row is None or row["count"] != expected:
            raise MemoryMigrationError("governed Memory source event range is missing")


def _postgres_values(namespace: str, record: MemoryRecord) -> tuple[object, ...]:
    return (
        namespace,
        record.memory_id,
        1,
        record.memory_type.value,
        None if record.status is MemoryStatus.DELETED else record.text,
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
        canonical_governed_memory_creation_key(record),
        canonical_governed_memory_content_hash(record),
        provenance_digest(record),
    )


def _scope_value(record: MemoryRecord) -> str:
    values = {
        MemoryVisibility.REPO: record.repo_id,
        MemoryVisibility.USER: record.user_id,
        MemoryVisibility.TENANT: record.tenant_id,
    }
    value = values[record.visibility]
    if value is None:
        raise MemoryMigrationError("governed Memory scope is missing")
    return value
