"""Namespace-scoped PostgreSQL delivery audit append/read adapter."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_core.ports.delivery_audit_store import DeliveryAuditStorePort
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


class PostgresDeliveryAuditStore(DeliveryAuditStorePort):
    """Append-only audit storage; command transaction ownership stays separate."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def append(self, record: DeliveryAuditRecord) -> DeliveryAuditRecord:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO control_plane_delivery_audit_records (
                    deployment_namespace, session_id, action, status, status_code,
                    policy_profile, idempotency_key, result_metadata, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._database.deployment_namespace,
                    record.session_id,
                    record.action,
                    record.status,
                    record.status_code,
                    record.policy_profile,
                    record.idempotency_key,
                    Jsonb(record.result_metadata),
                    record.created_at,
                ),
            )
        return record

    def list_for_session(self, session_id: SessionId) -> list[DeliveryAuditRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, action, status, status_code, policy_profile,
                       idempotency_key, result_metadata, created_at
                FROM control_plane_delivery_audit_records
                WHERE deployment_namespace = %s AND session_id = %s
                ORDER BY audit_id ASC
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchall()
        return [_record_from_row(row) for row in rows]


def _record_from_row(row: dict[str, Any]) -> DeliveryAuditRecord:
    metadata = row["result_metadata"]
    if not isinstance(metadata, dict):
        raise ValueError("delivery audit result_metadata must be a JSON object")
    created_at = row["created_at"]
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("delivery audit created_at must be timezone-aware")
    return DeliveryAuditRecord(
        session_id=SessionId(UUID(str(row["session_id"]))),
        action=str(row["action"]),
        status=str(row["status"]),
        status_code=int(row["status_code"]),
        policy_profile=row["policy_profile"],
        idempotency_key=row["idempotency_key"],
        result_metadata=json.loads(json.dumps(metadata)),
        created_at=created_at,
    )
