"""Deterministic SQLite snapshots and PostgreSQL cutover fencing."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sqlite3
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote
from uuid import UUID, uuid4

import psycopg
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import SessionEvent

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.projections import save_session_in_transaction

_SNAPSHOT_SCHEMA = "zebra.sqlite.snapshot.v1"
_IMPORT_IDENTITY = "zebra-postgres-migration-v1"
_T = TypeVar("_T")


class SnapshotIntegrityError(ValueError):
    """Raised when a snapshot or manifest is malformed or has been changed."""


class CutoverConflictError(RuntimeError):
    """Raised when a cutover transition would violate the active fence."""


class MigrationImportError(RuntimeError):
    """Raised when a snapshot cannot be imported without losing authority."""


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    table: str
    columns: tuple[str, ...]
    values: tuple[object, ...]

    def as_json(self) -> str:
        return _canonical_json(
            {"columns": self.columns, "table": self.table, "values": self.values}
        )


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    schema: str
    record_count: int
    records_sha256: str
    table_counts: tuple[tuple[str, int], ...]

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            _canonical_json(
                {
                    "record_count": self.record_count,
                    "records_sha256": self.records_sha256,
                    "schema": self.schema,
                    "table_counts": self.table_counts,
                }
            ).encode("utf-8")
        ).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "manifest_sha256": self.digest,
            "record_count": self.record_count,
            "records_sha256": self.records_sha256,
            "schema": self.schema,
            "table_counts": [list(item) for item in self.table_counts],
        }


@dataclass(frozen=True, slots=True)
class SQLiteSnapshot:
    records: tuple[SnapshotRecord, ...]
    manifest: SnapshotManifest


@dataclass(frozen=True, slots=True)
class MigrationImportReport:
    deployment_namespace: str
    event_count: int
    projection_count: int
    manifest_sha256: str


def export_sqlite_snapshot(
    database_path: str | Path,
    *,
    table_names: Sequence[str] | None = None,
) -> SQLiteSnapshot:
    """Read every user table from a consistent, read-only SQLite transaction."""
    path = Path(database_path)
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        raise SnapshotIntegrityError(f"cannot open SQLite snapshot source: {path}") from error
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        records: list[SnapshotRecord] = []
        table_counts: list[tuple[str, int]] = []
        available_tables = connection.execute(
            """SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name"""
        ).fetchall()
        available = tuple(str(row[0]) for row in available_tables)
        selected = available if table_names is None else tuple(sorted(set(table_names)))
        missing = set(selected) - set(available)
        if missing:
            raise SnapshotIntegrityError(
                f"requested SQLite snapshot tables do not exist: {', '.join(sorted(missing))}"
            )
        for table in selected:
            columns = tuple(
                str(column[1])
                for column in connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table)})"
                ).fetchall()
            )
            if not columns:
                raise SnapshotIntegrityError(f"table has no columns: {table}")
            rows = connection.execute(
                f"SELECT {_select_columns(columns)} FROM {_quote_identifier(table)}"
            ).fetchall()
            table_records = [
                SnapshotRecord(table, columns, tuple(_snapshot_value(value) for value in item))
                for item in rows
            ]
            table_records.sort(key=lambda item: item.as_json())
            records.extend(table_records)
            table_counts.append((table, len(table_records)))
        records.sort(key=lambda item: (item.table, item.as_json()))
        lines = "\n".join(record.as_json() for record in records)
        record_bytes = lines.encode("utf-8")
        manifest = SnapshotManifest(
            schema=_SNAPSHOT_SCHEMA,
            record_count=len(records),
            records_sha256=hashlib.sha256(record_bytes).hexdigest(),
            table_counts=tuple(table_counts),
        )
        connection.rollback()
        return SQLiteSnapshot(tuple(records), manifest)
    except (sqlite3.Error, SnapshotIntegrityError):
        connection.rollback()
        raise
    finally:
        connection.close()


def write_sqlite_snapshot(snapshot: SQLiteSnapshot, directory: str | Path) -> SnapshotManifest:
    """Write canonical JSONL and manifest files without modifying the source DB."""
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(record.as_json() for record in snapshot.records)
    (output / "records.jsonl").write_text(f"{lines}\n" if lines else "", encoding="utf-8")
    (output / "manifest.json").write_text(
        f"{_canonical_json(snapshot.manifest.as_dict())}\n", encoding="utf-8"
    )
    return snapshot.manifest


def load_sqlite_snapshot(directory: str | Path) -> SQLiteSnapshot:
    """Load and verify a previously written snapshot before any import."""
    root = Path(directory)
    try:
        manifest_data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        lines = [
            line
            for line in (root / "records.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotIntegrityError("snapshot files are unreadable") from error
    records: list[SnapshotRecord] = []
    for line in lines:
        try:
            value = json.loads(line)
            record = SnapshotRecord(
                table=str(value["table"]),
                columns=tuple(str(item) for item in value["columns"]),
                values=tuple(value["values"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SnapshotIntegrityError("snapshot record is malformed") from error
        if len(record.columns) != len(record.values):
            raise SnapshotIntegrityError("snapshot record column/value count mismatch")
        records.append(record)
    records.sort(key=lambda item: (item.table, item.as_json()))
    record_bytes = "\n".join(record.as_json() for record in records).encode("utf-8")
    try:
        manifest = SnapshotManifest(
            schema=str(manifest_data["schema"]),
            record_count=int(manifest_data["record_count"]),
            records_sha256=str(manifest_data["records_sha256"]),
            table_counts=tuple(
                (str(item[0]), int(item[1])) for item in manifest_data["table_counts"]
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SnapshotIntegrityError("snapshot manifest is malformed") from error
    if manifest.schema != _SNAPSHOT_SCHEMA or manifest.record_count != len(records):
        raise SnapshotIntegrityError("snapshot manifest count or schema mismatch")
    counts = {table: 0 for table, _ in manifest.table_counts}
    for record in records:
        counts[record.table] = counts.get(record.table, 0) + 1
    if manifest.records_sha256 != hashlib.sha256(record_bytes).hexdigest():
        raise SnapshotIntegrityError("snapshot records checksum mismatch")
    if tuple(sorted(counts.items())) != tuple(sorted(manifest.table_counts)):
        raise SnapshotIntegrityError("snapshot table counts mismatch")
    if manifest_data.get("manifest_sha256") != manifest.digest:
        raise SnapshotIntegrityError("snapshot manifest checksum mismatch")
    return SQLiteSnapshot(tuple(records), manifest)


def import_sqlite_event_snapshot(
    directory: str | Path,
    postgres_dsn: str,
    *,
    deployment_namespace: str,
    importer_identity: str,
) -> MigrationImportReport:
    """Import Events first, then rebuild Sessions from the imported Event stream."""
    snapshot = load_sqlite_snapshot(directory)
    if importer_identity != _IMPORT_IDENTITY:
        raise MigrationImportError("restricted migration importer identity required")
    records_by_table: dict[str, list[SnapshotRecord]] = {}
    for record in snapshot.records:
        records_by_table.setdefault(record.table, []).append(record)
    unsupported = set(records_by_table) - {"session_events", "session_projections"}
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise MigrationImportError(f"snapshot contains unsupported authoritative tables: {names}")
    events = _events_from_records(records_by_table.get("session_events", []))
    database = PostgresDatabase(postgres_dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"migration-import:{deployment_namespace}",),
        )
        _require_empty_import_target(connection)
        grouped: dict[str, list[SessionEvent]] = {}
        for event in events:
            append_event_in_transaction(connection, deployment_namespace, event)
            grouped.setdefault(str(event.session_id), []).append(event)
        for session_events in grouped.values():
            save_session_in_transaction(
                connection,
                deployment_namespace,
                rebuild_session(session_events),
            )
    return MigrationImportReport(
        deployment_namespace=deployment_namespace,
        event_count=len(events),
        projection_count=len(grouped),
        manifest_sha256=snapshot.manifest.digest,
    )


class PostgresCutoverStore:
    """Namespace-scoped cutover state; runtime writes must use ``run_guarded``."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def prepare(self, *, manifest_sha256: str, cutover_id: UUID | None = None) -> UUID:
        identifier = cutover_id or uuid4()
        _require_digest(manifest_sha256)
        with self._database.connect() as connection:
            connection.execute(
                """INSERT INTO control_plane_cutovers
                (deployment_namespace, cutover_id, state, manifest_sha256)
                VALUES (%s, %s, 'prepared', %s)""",
                (self._database.deployment_namespace, identifier, manifest_sha256),
            )
        return identifier

    def verify(self, cutover_id: UUID, *, manifest_sha256: str) -> None:
        self._transition(cutover_id, "prepared", "verified", manifest_sha256)

    def activate(self, cutover_id: UUID, *, manifest_sha256: str) -> None:
        self._transition(cutover_id, "verified", "active", manifest_sha256)

    def _transition(
        self, cutover_id: UUID, expected: str, target: str, manifest_sha256: str
    ) -> None:
        _require_digest(manifest_sha256)
        try:
            with self._database.connect() as connection:
                cursor = connection.execute(
                    """UPDATE control_plane_cutovers
                    SET state = %s, verified_at = CASE WHEN %s = 'verified'
                        THEN transaction_timestamp() ELSE verified_at END,
                        activated_at = CASE WHEN %s = 'active'
                        THEN transaction_timestamp() ELSE activated_at END
                    WHERE deployment_namespace = %s AND cutover_id = %s
                      AND state = %s AND manifest_sha256 = %s""",
                    (
                        target,
                        target,
                        target,
                        self._database.deployment_namespace,
                        cutover_id,
                        expected,
                        manifest_sha256,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CutoverConflictError(f"invalid cutover transition to {target}")
        except psycopg.errors.UniqueViolation as error:
            raise CutoverConflictError("another active cutover already exists") from error

    def run_guarded(
        self, cutover_id: UUID, manifest_sha256: str, action: Callable[[Any], _T]
    ) -> _T:
        _require_digest(manifest_sha256)
        with self._database.connect() as connection:
            _assert_active(
                connection,
                self._database.deployment_namespace,
                cutover_id,
                manifest_sha256,
            )
            return action(connection)


def _assert_active(connection: Any, namespace: str, cutover_id: UUID, digest: str) -> None:
    row = connection.execute(
        """SELECT state FROM control_plane_cutovers
        WHERE deployment_namespace = %s AND cutover_id = %s
          AND manifest_sha256 = %s""",
        (namespace, cutover_id, digest),
    ).fetchone()
    if row is None or row["state"] != "active":
        raise CutoverConflictError("runtime write requires an active matching cutover")


def _events_from_records(records: Sequence[SnapshotRecord]) -> tuple[SessionEvent, ...]:
    events: list[SessionEvent] = []
    for record in records:
        values = _record_values(
            record,
            {
                "event_id",
                "session_id",
                "sequence",
                "event_type",
                "payload",
                "actor",
                "created_at",
                "causation_id",
                "correlation_id",
                "idempotency_key",
                "policy_version",
                "model_profile",
            },
        )
        payload = values["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as error:
                raise MigrationImportError("session Event payload is not JSON") from error
        if not isinstance(payload, dict):
            raise MigrationImportError("session Event payload must be an object")
        try:
            events.append(SessionEvent.model_validate({**values, "payload": payload}))
        except ValueError as error:
            raise MigrationImportError("session Event record failed validation") from error
    events.sort(key=lambda event: (str(event.session_id), event.sequence))
    expected: dict[str, int] = {}
    for event in events:
        sequence = expected.get(str(event.session_id), 0)
        if event.sequence != sequence:
            raise MigrationImportError("session Event sequence is not contiguous")
        expected[str(event.session_id)] = sequence + 1
    return tuple(events)


def _record_values(record: SnapshotRecord, expected: set[str]) -> dict[str, object]:
    if set(record.columns) != expected or len(record.columns) != len(record.values):
        raise MigrationImportError(f"unexpected {record.table} column contract")
    return dict(zip(record.columns, record.values, strict=True))


def _require_empty_import_target(connection: Any) -> None:
    for table in (
        "session_events",
        "session_streams",
        "session_projections",
        "control_plane_cutovers",
    ):
        row = connection.execute(f"SELECT count(*) AS count FROM {table}").fetchone()
        if row is None or row["count"] != 0:
            raise MigrationImportError("PostgreSQL import target must be empty")


def _require_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("manifest checksum must be a lowercase SHA-256 digest")


def _snapshot_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    return _normalize(value)


def _canonical_json(value: object) -> str:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SnapshotIntegrityError("non-finite SQLite value cannot be canonicalized")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_normalize(item) for item in value]
    return value


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _select_columns(columns: tuple[str, ...]) -> str:
    return ", ".join(_quote_identifier(column) for column in columns)
