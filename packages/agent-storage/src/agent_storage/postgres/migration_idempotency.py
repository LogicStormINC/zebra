"""Fail-closed replay of SQLite idempotency receipts into PostgreSQL."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from agent_storage.postgres.migration_snapshot import SnapshotRecord


class IdempotencyMigrationError(ValueError):
    """Raised when an idempotency receipt cannot be imported exactly."""


@dataclass(frozen=True, slots=True)
class IdempotencyReplayReport:
    record_count: int


def replay_idempotency_snapshot(
    connection: Any,
    deployment_namespace: str,
    records_by_table: Mapping[str, Sequence[SnapshotRecord]],
) -> IdempotencyReplayReport:
    rows = tuple(
        _parse(record) for record in records_by_table.get("idempotency_records", ())
    )
    identities = {(row["action"], row["idempotency_key"]) for row in rows}
    if len(identities) != len(rows):
        raise IdempotencyMigrationError("idempotency identities are duplicated")
    for row in rows:
        connection.execute(
            """INSERT INTO control_plane_idempotency_records (
                deployment_namespace, action, idempotency_key, request_hash,
                status_code, response_body, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                deployment_namespace, row["action"], row["idempotency_key"],
                row["request_hash"], row["status_code"], Jsonb(row["response_body"]),
                row["created_at"],
            ),
        )
    return IdempotencyReplayReport(record_count=len(rows))


def _parse(record: SnapshotRecord) -> dict[str, object]:
    values = _record_values(
        record,
        {"action", "idempotency_key", "request_hash", "status_code", "response_body", "created_at"},
    )
    action = _text(values["action"], "action")
    key = _text(values["idempotency_key"], "idempotency_key")
    request_hash = _text(values["request_hash"], "request_hash")
    status_code = values["status_code"]
    if isinstance(status_code, bool):
        raise IdempotencyMigrationError("idempotency status_code is invalid")
    try:
        if isinstance(status_code, int | str):
            status_code = int(status_code)
        else:
            raise TypeError
    except (TypeError, ValueError) as error:
        raise IdempotencyMigrationError("idempotency status_code is invalid") from error
    if not 100 <= status_code <= 599:
        raise IdempotencyMigrationError("idempotency status_code is outside HTTP range")
    try:
        raw_body = values["response_body"]
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise IdempotencyMigrationError("idempotency response_body is malformed") from error
    if not isinstance(body, dict):
        raise IdempotencyMigrationError("idempotency response_body must be an object")
    created_at = _timestamp(values["created_at"])
    return {
        "action": action,
        "idempotency_key": key,
        "request_hash": request_hash,
        "status_code": status_code,
        "response_body": body,
        "created_at": created_at,
    }


def _record_values(record: SnapshotRecord, expected: set[str]) -> dict[str, object]:
    if set(record.columns) != expected or len(record.columns) != len(record.values):
        raise IdempotencyMigrationError(f"unexpected {record.table} column contract")
    return dict(zip(record.columns, record.values, strict=True))


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdempotencyMigrationError(f"idempotency {field} must not be blank")
    return value


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise IdempotencyMigrationError("idempotency created_at is invalid") from error
    if parsed.tzinfo is None:
        raise IdempotencyMigrationError("idempotency created_at must be timezone-aware")
    return parsed
