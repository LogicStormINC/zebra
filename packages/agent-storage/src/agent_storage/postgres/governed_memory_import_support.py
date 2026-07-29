"""Content-free reports and SQLite row preparation for governed Memory import."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from agent_core.domain.governed_memories import (
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility

from agent_storage.postgres.governed_memory_rows import provenance_digest

IMPORT_CONTRACT = "governed-memory-sqlite-import/1"
_COLUMNS = (
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
)


@dataclass(frozen=True)
class GovernedMemoryImportQuarantine:
    memory_id: str | None
    code: str
    evidence_digest: str


@dataclass(frozen=True)
class GovernedMemoryImportReport:
    schema: str
    deployment_namespace: str
    source_count: int
    imported_count: int
    replayed_count: int
    source_groups: tuple[tuple[str, str, str, str, int], ...]
    target_groups: tuple[tuple[str, str, str, str, int], ...]
    fts_rebuilt: bool
    quarantine: tuple[GovernedMemoryImportQuarantine, ...] = ()


class GovernedMemoryImportError(ValueError):
    def __init__(self, report: GovernedMemoryImportReport) -> None:
        super().__init__("governed Memory import failed; inspect content-free report")
        self.report = report


@dataclass(frozen=True)
class _PreparedRow:
    record: MemoryRecord
    creation_key: str
    content_digest: str
    provenance_digest: str


def legacy_import_creation_key_v1(record: MemoryRecord) -> str:
    """Freeze v1 to the authority model's canonical creation identity."""
    return canonical_governed_memory_creation_key(record)


def _read_source(
    sqlite_path: str | Path, *, page_size: int
) -> tuple[tuple[_PreparedRow, ...], int, tuple[GovernedMemoryImportQuarantine, ...]]:
    uri = Path(sqlite_path).expanduser().resolve().as_uri() + "?mode=ro"
    prepared: list[_PreparedRow] = []
    issues: list[GovernedMemoryImportQuarantine] = []
    source_count = 0
    last_id = ""
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            while True:
                rows = connection.execute(
                    f"""SELECT {", ".join(_COLUMNS)} FROM memory_records
                    WHERE memory_id > ? ORDER BY memory_id LIMIT ?""",
                    (last_id, page_size),
                ).fetchall()
                if not rows:
                    break
                source_count += len(rows)
                for row in rows:
                    last_id = str(row["memory_id"])
                    try:
                        record = _record_from_sqlite(row)
                        prepared.append(
                            _PreparedRow(
                                record=record,
                                creation_key=legacy_import_creation_key_v1(record),
                                content_digest=canonical_governed_memory_content_hash(record),
                                provenance_digest=provenance_digest(record),
                            )
                        )
                    except (TypeError, ValueError) as error:
                        issues.append(_issue(last_id or None, type(error).__name__))
    except sqlite3.Error as error:
        issues.append(_issue(None, f"sqlite_{type(error).__name__}"))
    issues.extend(_source_relationship_issues(prepared))
    return tuple(prepared), source_count, tuple(issues)


def _source_relationship_issues(
    prepared: list[_PreparedRow],
) -> list[GovernedMemoryImportQuarantine]:
    issues: list[GovernedMemoryImportQuarantine] = []
    ids = [item.record.memory_id for item in prepared]
    keys = [item.creation_key for item in prepared]
    if len(ids) != len(set(ids)):
        issues.append(_issue(None, "duplicate_source_memory_id"))
    if len(keys) != len(set(keys)):
        issues.append(_issue(None, "duplicate_source_creation_key"))
    singleton = Counter(
        (
            item.record.visibility.value,
            _scope_value(item.record),
            item.record.memory_type.value,
        )
        for item in prepared
        if item.record.status is MemoryStatus.CONFIRMED
        and item.record.memory_type
        in {MemoryType.PROJECT_RULE, MemoryType.PROCEDURE, MemoryType.ARCHITECTURE_FACT}
    )
    if any(count > 1 for count in singleton.values()):
        issues.append(_issue(None, "multiple_confirmed_singleton"))
    return issues


def _postgres_values(namespace: str, item: _PreparedRow) -> tuple[object, ...]:
    record = item.record
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
        item.creation_key,
        item.content_digest,
        item.provenance_digest,
    )


def _record_from_sqlite(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(row["memory_id"])),
        memory_type=MemoryType(row["memory_type"]),
        text=row["text"],
        confidence=row["confidence"],
        status=MemoryStatus(row["status"]),
        visibility=MemoryVisibility(row["visibility"]),
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        repo_id=row["repo_id"],
        source_session_id=(
            None if row["source_session_id"] is None else SessionId(UUID(row["source_session_id"]))
        ),
        source_event_start=row["source_event_start"],
        source_event_end=row["source_event_end"],
        source_commit_sha=row["source_commit_sha"],
        superseded_by=(
            None if row["superseded_by"] is None else MemoryId(UUID(row["superseded_by"]))
        ),
        expires_at=_optional_datetime(row["expires_at"]),
        created_at=_required_datetime(row["created_at"]),
        updated_at=_required_datetime(row["updated_at"]),
    )


def _record_from_target(row: dict[str, Any]) -> MemoryRecord:
    values = dict(row)
    if values["status"] == MemoryStatus.DELETED.value:
        values["text"] = "deleted"
    return MemoryRecord.model_validate({key: values[key] for key in _COLUMNS})


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _required_datetime(value)


def _required_datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _scope_value(record: MemoryRecord) -> str:
    value = {
        MemoryVisibility.REPO: record.repo_id,
        MemoryVisibility.USER: record.user_id,
        MemoryVisibility.TENANT: record.tenant_id,
    }[record.visibility]
    assert value is not None
    return value


def _group_counts(records: Iterable[MemoryRecord]) -> tuple[tuple[str, str, str, str, int], ...]:
    counts = Counter(
        (item.status.value, item.visibility.value, item.memory_type.value, _scope_value(item))
        for item in records
    )
    return tuple((*key, count) for key, count in sorted(counts.items()))


def _issue(memory_id: str | None, code: str) -> GovernedMemoryImportQuarantine:
    evidence = json.dumps({"memory_id": memory_id, "code": code}, sort_keys=True).encode()
    return GovernedMemoryImportQuarantine(memory_id, code, hashlib.sha256(evidence).hexdigest())


def _report(
    namespace: str,
    source_count: int,
    source_groups: tuple[tuple[str, str, str, str, int], ...],
    issues: Iterable[GovernedMemoryImportQuarantine],
    *,
    target_groups: tuple[tuple[str, str, str, str, int], ...] = (),
) -> GovernedMemoryImportReport:
    return GovernedMemoryImportReport(
        IMPORT_CONTRACT,
        namespace,
        source_count,
        0,
        0,
        source_groups,
        target_groups,
        False,
        tuple(issues),
    )
