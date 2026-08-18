"""Namespace-scoped PostgreSQL idempotency records for cloud commands."""

import json
from datetime import datetime
from typing import Any

from agent_core.ports.idempotency_store import IdempotencyRecord, IdempotencyStorePort
from psycopg.types.json import Jsonb

from agent_storage.idempotency import IdempotencyConflictError
from agent_storage.postgres.database import PostgresDatabase


class PostgresIdempotencyStore(IdempotencyStorePort):
    """Persist API-neutral receipts without selecting an API or runtime profile."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def get(self, *, action: str, idempotency_key: str) -> IdempotencyRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT action, idempotency_key, request_hash, status_code,
                       response_body, created_at
                FROM control_plane_idempotency_records
                WHERE deployment_namespace = %s AND action = %s
                  AND idempotency_key = %s
                """,
                (self._database.deployment_namespace, action, idempotency_key),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def save(self, record: IdempotencyRecord) -> IdempotencyRecord:
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT action, idempotency_key, request_hash, status_code,
                       response_body, created_at
                FROM control_plane_idempotency_records
                WHERE deployment_namespace = %s AND action = %s
                  AND idempotency_key = %s
                FOR UPDATE
                """,
                (namespace, record.action, record.idempotency_key),
            ).fetchone()
            if existing is not None:
                stored = _record_from_row(existing)
                if stored.request_hash != record.request_hash:
                    raise IdempotencyConflictError("idempotency key reused with different request")
                return stored
            inserted = connection.execute(
                """
                INSERT INTO control_plane_idempotency_records (
                    deployment_namespace, action, idempotency_key, request_hash,
                    status_code, response_body, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, action, idempotency_key) DO NOTHING
                RETURNING action, idempotency_key, request_hash, status_code,
                          response_body, created_at
                """,
                (
                    namespace,
                    record.action,
                    record.idempotency_key,
                    record.request_hash,
                    record.status_code,
                    Jsonb(record.response_body),
                    record.created_at,
                ),
            ).fetchone()
            if inserted is not None:
                return _record_from_row(inserted)
            replay = connection.execute(
                """
                SELECT action, idempotency_key, request_hash, status_code,
                       response_body, created_at
                FROM control_plane_idempotency_records
                WHERE deployment_namespace = %s AND action = %s
                  AND idempotency_key = %s
                FOR UPDATE
                """,
                (namespace, record.action, record.idempotency_key),
            ).fetchone()
            if replay is None:
                raise RuntimeError("idempotency insert disappeared before replay read")
            stored = _record_from_row(replay)
            if stored.request_hash != record.request_hash:
                raise IdempotencyConflictError("idempotency key reused with different request")
            return stored


def _record_from_row(row: dict[str, Any]) -> IdempotencyRecord:
    response_body = row["response_body"]
    if not isinstance(response_body, dict):
        raise ValueError("idempotency response_body must be a JSON object")
    return IdempotencyRecord(
        action=str(row["action"]),
        idempotency_key=str(row["idempotency_key"]),
        request_hash=str(row["request_hash"]),
        status_code=int(row["status_code"]),
        response_body=json.loads(json.dumps(response_body)),
        created_at=_aware_datetime(row["created_at"]),
    )


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("idempotency created_at must be timezone-aware")
    return value
