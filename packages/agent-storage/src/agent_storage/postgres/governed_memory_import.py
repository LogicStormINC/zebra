"""Explicit, offline SQLite to PostgreSQL governed Memory import."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from agent_core.domain.governed_memories import GovernedMemoryConflictError
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryStatus, MemoryType

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.governed_memory_import_support import (
    IMPORT_CONTRACT,
    GovernedMemoryImportError,
    GovernedMemoryImportQuarantine,
    GovernedMemoryImportReport,
    _group_counts,
    _issue,
    _postgres_values,
    _PreparedRow,
    _read_source,
    _record_from_target,
    _report,
    _scope_value,
    legacy_import_creation_key_v1,
)

__all__ = [
    "GovernedMemoryImportError",
    "GovernedMemoryImportQuarantine",
    "GovernedMemoryImportReport",
    "import_sqlite_governed_memories",
    "legacy_import_creation_key_v1",
]


def import_sqlite_governed_memories(
    sqlite_path: str | Path,
    postgres_dsn: str,
    *,
    deployment_namespace: str,
    page_size: int = 500,
) -> GovernedMemoryImportReport:
    """Preflight the complete read-only source, then import in one PG transaction."""
    if page_size < 1 or page_size > 5000:
        raise ValueError("page_size must be between 1 and 5000")
    prepared, source_count, source_issues = _read_source(sqlite_path, page_size=page_size)
    source_groups = _group_counts(item.record for item in prepared)
    if source_issues:
        raise GovernedMemoryImportError(
            _report(
                deployment_namespace,
                source_count,
                source_groups,
                source_issues,
            )
        )

    database = PostgresDatabase(postgres_dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"memory-import:{deployment_namespace}",),
        )
        connection.execute("LOCK TABLE governed_memory_records IN SHARE ROW EXCLUSIVE MODE")
        issues = _preflight_target(connection, deployment_namespace, prepared)
        if issues:
            raise GovernedMemoryImportError(
                _report(deployment_namespace, source_count, source_groups, issues)
            )
        imported = 0
        replayed = 0
        for item in prepared:
            row = _lock_identity(connection, deployment_namespace, item)
            if row is not None:
                _require_same_row(item, row)
                replayed += 1
                continue
            connection.execute(
                f"""
                INSERT INTO governed_memory_records (
                    deployment_namespace, memory_id, revision, memory_type, text,
                    confidence, status, visibility, tenant_id, user_id, repo_id,
                    authority_issuer, namespace_id, definition_id,
                    source_session_id, source_event_start, source_event_end,
                    source_commit_sha, superseded_by, expires_at, created_at, updated_at,
                    creation_key, content_digest, provenance_digest
                ) VALUES ({", ".join(["%s"] * 25)})
                """,
                _postgres_values(deployment_namespace, item),
            )
            imported += 1
        target_rows = _target_rows(
            connection,
            deployment_namespace,
            tuple(item.record.memory_id for item in prepared),
        )
        target_groups = _group_counts(_record_from_target(row) for row in target_rows)
        if len(target_rows) != source_count or target_groups != source_groups:
            raise GovernedMemoryImportError(
                _report(
                    deployment_namespace,
                    source_count,
                    source_groups,
                    (_issue(None, "target_count_or_group_mismatch"),),
                    target_groups=target_groups,
                )
            )
        connection.execute("REINDEX INDEX governed_memory_search")
    return GovernedMemoryImportReport(
        schema=IMPORT_CONTRACT,
        deployment_namespace=deployment_namespace,
        source_count=source_count,
        imported_count=imported,
        replayed_count=replayed,
        source_groups=source_groups,
        target_groups=target_groups,
        fts_rebuilt=True,
    )


def _preflight_target(
    connection: Any, namespace: str, prepared: tuple[_PreparedRow, ...]
) -> tuple[GovernedMemoryImportQuarantine, ...]:
    issues: list[GovernedMemoryImportQuarantine] = []
    existing_sessions = {
        row["session_id"]
        for row in connection.execute(
            "SELECT session_id FROM session_streams WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchall()
    }
    for item in prepared:
        record = item.record
        if (
            record.source_session_id is not None
            and record.source_session_id not in existing_sessions
        ):
            issues.append(_issue(str(record.memory_id), "missing_source_session"))
        if record.source_session_id is not None and record.source_event_start is not None:
            row = connection.execute(
                """SELECT count(*) AS count FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                  AND sequence BETWEEN %s AND %s""",
                (
                    namespace,
                    record.source_session_id,
                    record.source_event_start,
                    record.source_event_end,
                ),
            ).fetchone()
            assert record.source_event_end is not None
            expected = record.source_event_end - record.source_event_start + 1
            if row["count"] != expected:
                issues.append(_issue(str(record.memory_id), "missing_source_event"))
        try:
            row = _find_identity(connection, namespace, item)
            if row is not None:
                _require_same_row(item, row)
        except GovernedMemoryImportError as error:
            issues.extend(error.report.quarantine)
        if record.status is MemoryStatus.CONFIRMED and record.memory_type in {
            MemoryType.PROJECT_RULE,
            MemoryType.PROCEDURE,
            MemoryType.ARCHITECTURE_FACT,
        }:
            collision = connection.execute(
                f"""SELECT 1 FROM governed_memory_records
                WHERE deployment_namespace = %s AND status = 'confirmed'
                  AND visibility = %s AND memory_type = %s
                  AND {_scope_column(record.visibility.value)} = %s
                  AND memory_id != %s LIMIT 1""",
                (
                    namespace,
                    record.visibility.value,
                    record.memory_type.value,
                    _scope_value(record),
                    record.memory_id,
                ),
            ).fetchone()
            if collision is not None:
                issues.append(_issue(str(record.memory_id), "confirmed_singleton_conflict"))
    source_ids = {item.record.memory_id: item.record for item in prepared}
    for item in prepared:
        target_id = item.record.superseded_by
        if target_id is None:
            continue
        target = source_ids.get(target_id)
        if target is not None:
            if target.status is MemoryStatus.DELETED:
                issues.append(_issue(str(item.record.memory_id), "deleted_superseded_target"))
            continue
        row = connection.execute(
            """SELECT status FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = %s""",
            (namespace, target_id),
        ).fetchone()
        if row is None or row["status"] == MemoryStatus.DELETED.value:
            issues.append(_issue(str(item.record.memory_id), "missing_superseded_target"))
    return tuple(issues)


def _find_identity(connection: Any, namespace: str, item: _PreparedRow) -> dict[str, Any] | None:
    return _identity(connection, namespace, item, lock=False)


def _lock_identity(connection: Any, namespace: str, item: _PreparedRow) -> dict[str, Any] | None:
    return _identity(connection, namespace, item, lock=True)


def _identity(
    connection: Any, namespace: str, item: _PreparedRow, *, lock: bool
) -> dict[str, Any] | None:
    rows = connection.execute(
        f"""SELECT * FROM governed_memory_records
        WHERE deployment_namespace = %s AND (memory_id = %s OR creation_key = %s)
        ORDER BY memory_id {"FOR UPDATE" if lock else ""}""",
        (namespace, item.record.memory_id, item.creation_key),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise _conflict(namespace, item, "split_id_and_creation_key")
    return cast(dict[str, Any], rows[0])


def _require_same_row(item: _PreparedRow, row: dict[str, Any]) -> None:
    expected = _postgres_values(str(row["deployment_namespace"]), item)
    columns = (
        "deployment_namespace",
        "memory_id",
        "revision",
        "memory_type",
        "text",
        "confidence",
        "status",
        "visibility",
        "tenant_id",
        "user_id",
        "repo_id",
        "authority_issuer",
        "namespace_id",
        "definition_id",
        "source_session_id",
        "source_event_start",
        "source_event_end",
        "source_commit_sha",
        "superseded_by",
        "expires_at",
        "created_at",
        "updated_at",
        "creation_key",
        "content_digest",
        "provenance_digest",
    )
    if tuple(row[column] for column in columns) != expected:
        raise _conflict(str(row["deployment_namespace"]), item, "existing_authority_conflict")


def _conflict(namespace: str, item: _PreparedRow, code: str) -> GovernedMemoryImportError:
    return GovernedMemoryImportError(
        _report(
            namespace,
            1,
            _group_counts((item.record,)),
            (_issue(str(item.record.memory_id), code),),
        )
    )


def _target_rows(
    connection: Any, namespace: str, memory_ids: tuple[MemoryId, ...]
) -> list[dict[str, Any]]:
    if not memory_ids:
        return []
    return cast(
        list[dict[str, Any]],
        connection.execute(
            """SELECT * FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = ANY(%s)
            ORDER BY memory_id""",
            (namespace, list(memory_ids)),
        ).fetchall(),
    )


def _scope_column(visibility: str) -> str:
    try:
        return {"repo": "repo_id", "user": "user_id", "tenant": "tenant_id"}[visibility]
    except KeyError as error:
        raise GovernedMemoryConflictError("invalid Memory visibility") from error
