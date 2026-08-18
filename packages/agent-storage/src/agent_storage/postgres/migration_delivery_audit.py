"""Replay legacy delivery audit rows with an explicit source-order extension."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from psycopg.types.json import Jsonb

from agent_storage.postgres.migration_snapshot import SnapshotRecord


class DeliveryAuditMigrationError(ValueError):
    """Raised when legacy audit ordering or row data cannot be proven."""


@dataclass(frozen=True, slots=True)
class DeliveryAuditReplayReport:
    record_count: int


_ROWID_COLUMN = "__zebra_source_rowid"
_COLUMNS = {
    "session_id",
    "action",
    "status",
    "status_code",
    "policy_profile",
    "idempotency_key",
    "result_metadata",
    "created_at",
    _ROWID_COLUMN,
}


def replay_delivery_audit_snapshot(
    connection: Any,
    deployment_namespace: str,
    records_by_table: Mapping[str, Sequence[SnapshotRecord]],
) -> DeliveryAuditReplayReport:
    rows = tuple(_parse(record) for record in records_by_table.get("delivery_audit_records", ()))
    ordinals = [row["source_rowid"] for row in rows]
    if len(ordinals) != len(set(ordinals)):
        raise DeliveryAuditMigrationError("delivery audit source rowids are duplicated")
    rows = tuple(sorted(rows, key=lambda row: cast(int, row["source_rowid"])))
    for row in rows:
        session = connection.execute(
            """SELECT 1 FROM session_streams
            WHERE deployment_namespace = %s AND session_id = %s""",
            (deployment_namespace, row["session_id"]),
        ).fetchone()
        if session is None:
            raise DeliveryAuditMigrationError("delivery audit session is missing")
        connection.execute(
            """INSERT INTO control_plane_delivery_audit_records (
                deployment_namespace, session_id, action, status, status_code,
                policy_profile, idempotency_key, result_metadata, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                deployment_namespace,
                row["session_id"],
                row["action"],
                row["status"],
                row["status_code"],
                row["policy_profile"],
                row["idempotency_key"],
                Jsonb(row["result_metadata"]),
                row["created_at"],
            ),
        )
    return DeliveryAuditReplayReport(record_count=len(rows))


def _parse(record: SnapshotRecord) -> dict[str, object]:
    values = _record_values(record)
    try:
        session_id = UUID(str(values["session_id"]))
    except (TypeError, ValueError) as error:
        raise DeliveryAuditMigrationError("delivery audit session_id is invalid") from error
    source_rowid = values[_ROWID_COLUMN]
    if isinstance(source_rowid, bool) or not isinstance(source_rowid, int) or source_rowid < 0:
        raise DeliveryAuditMigrationError("delivery audit source rowid is invalid")
    action = _text(values["action"], "action")
    status = _text(values["status"], "status")
    status_code = values["status_code"]
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise DeliveryAuditMigrationError("delivery audit status_code is invalid")
    if not 100 <= status_code <= 599:
        raise DeliveryAuditMigrationError("delivery audit status_code is outside HTTP range")
    metadata = values["result_metadata"]
    try:
        metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise DeliveryAuditMigrationError("delivery audit metadata is malformed") from error
    if not isinstance(metadata, dict):
        raise DeliveryAuditMigrationError("delivery audit metadata must be an object")
    created_at = _timestamp(values["created_at"])
    return {
        "session_id": session_id,
        "source_rowid": source_rowid,
        "action": action,
        "status": status,
        "status_code": status_code,
        "policy_profile": _optional_text(values["policy_profile"], "policy_profile"),
        "idempotency_key": _optional_text(values["idempotency_key"], "idempotency_key"),
        "result_metadata": metadata,
        "created_at": created_at,
    }


def _record_values(record: SnapshotRecord) -> dict[str, object]:
    if set(record.columns) != _COLUMNS or len(record.columns) != len(record.values):
        raise DeliveryAuditMigrationError(
            "delivery audit snapshot requires snapshot v2 source rowids"
        )
    return dict(zip(record.columns, record.values, strict=True))


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeliveryAuditMigrationError(f"delivery audit {field} must not be blank")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise DeliveryAuditMigrationError("delivery audit created_at is invalid") from error
    if parsed.tzinfo is None:
        raise DeliveryAuditMigrationError("delivery audit created_at must be timezone-aware")
    return parsed
