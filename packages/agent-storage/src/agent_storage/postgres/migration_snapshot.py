"""Canonical, read-only SQLite snapshot export for PostgreSQL migration."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sqlite3
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

_SNAPSHOT_SCHEMA = "zebra.sqlite.snapshot.v1"
_SNAPSHOT_SCHEMA_WITH_ROWIDS = "zebra.sqlite.snapshot.v2"
_ROWID_COLUMN = "__zebra_source_rowid"


class SnapshotIntegrityError(ValueError):
    """Raised when a snapshot or manifest is malformed or has been changed."""


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


def export_sqlite_snapshot(
    database_path: str | Path,
    *,
    table_names: Sequence[str] | None = None,
    include_rowids: Sequence[str] = (),
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
        rowid_tables = set(include_rowids)
        if rowid_tables - set(selected):
            raise SnapshotIntegrityError("rowid capture requires the table to be selected")
        for table in selected:
            columns = tuple(
                str(column[1])
                for column in connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table)})"
                ).fetchall()
            )
            if not columns:
                raise SnapshotIntegrityError(f"table has no columns: {table}")
            if table in rowid_tables:
                if _ROWID_COLUMN in columns:
                    raise SnapshotIntegrityError(f"reserved rowid column is present: {table}")
                snapshot_columns = (*columns, _ROWID_COLUMN)
                rows = connection.execute(
                    f"SELECT {_select_columns(columns)}, "
                    f"rowid AS {_quote_identifier(_ROWID_COLUMN)} "
                    f"FROM {_quote_identifier(table)}"
                ).fetchall()
            else:
                snapshot_columns = columns
                rows = connection.execute(
                    f"SELECT {_select_columns(columns)} FROM {_quote_identifier(table)}"
                ).fetchall()
            table_records = [
                SnapshotRecord(
                    table, snapshot_columns, tuple(_snapshot_value(value) for value in item)
                )
                for item in rows
            ]
            table_records.sort(key=lambda item: item.as_json())
            records.extend(table_records)
            table_counts.append((table, len(table_records)))
        records.sort(key=lambda item: (item.table, item.as_json()))
        record_bytes = "\n".join(record.as_json() for record in records).encode("utf-8")
        manifest = SnapshotManifest(
            schema=_SNAPSHOT_SCHEMA_WITH_ROWIDS if rowid_tables else _SNAPSHOT_SCHEMA,
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
    if manifest.schema not in {_SNAPSHOT_SCHEMA, _SNAPSHOT_SCHEMA_WITH_ROWIDS}:
        raise SnapshotIntegrityError("snapshot manifest schema is unsupported")
    if manifest.record_count != len(records):
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
