"""Durable private-executor start/exit evidence, independent of Session event locks."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from typing import Any

import psycopg
from agent_core.domain.leases import LeaseLostError
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.force_stop_signal import STOP_ANCESTRY
from agent_storage.postgres.leases import assert_current_lease_fence


def _connection(
    database: PostgresDatabase, *, autocommit: bool = False
) -> psycopg.Connection[dict[str, Any]]:
    # Emergency control must not inherit a stuck/expired harness I/O work unit.
    options = str(conninfo_to_dict(database._dsn).get("options") or "")
    return psycopg.connect(
        database._dsn,
        row_factory=dict_row,
        connect_timeout=2,
        autocommit=autocommit,
        options=options + " -c statement_timeout=1500 -c lock_timeout=250",
    )


@contextmanager
def executor_monitor(database: PostgresDatabase, sid: Any) -> Iterator[Callable[[], bool]]:
    connection: psycopg.Connection[dict[str, Any]] | None = None

    def cancelled() -> bool:
        nonlocal connection
        if connection is None or connection.closed:
            connection = _connection(database, autocommit=True)
        try:
            row = connection.execute(
                "SELECT (SELECT status FROM session_projections WHERE "
                "deployment_namespace=%(namespace)s AND session_id=%(sid)s) AS status, "
                "EXISTS(" + STOP_ANCESTRY + ") AS forced",
                {"namespace": database.deployment_namespace, "sid": sid},
            ).fetchone()
            return bool(row and (row["forced"] or row["status"] == "cancelled"))
        except Exception:
            connection.close()
            connection = None
            raise

    try:
        yield cancelled
    finally:
        if connection is not None:
            connection.close()


def executor_key(sid: Any, fence: Any) -> str:
    raw = json.dumps([str(sid), fence.model_dump(mode="json")], sort_keys=True).encode()
    return f"{sid}:{sha256(raw).hexdigest()}"


def register_executor(database: PostgresDatabase, sid: Any, fence: Any) -> None:
    with _connection(database) as connection:
        connection.execute("SET LOCAL lock_timeout='250ms'")
        assert_current_lease_fence(connection, database.deployment_namespace, sid, fence)
        if not _save(connection, database.deployment_namespace, "executor_started", sid, fence):
            raise LeaseLostError("executor fence was already started")


def acknowledge_executor(database: PostgresDatabase, sid: Any, fence: Any) -> None:
    with _connection(database) as connection:
        # Registered older attempts may acknowledge their OWN exit after takeover;
        # they cannot attest the successor's exit or restore its revoked lease.
        if _receipt(connection, database.deployment_namespace, "executor_started", sid, fence):
            _save(connection, database.deployment_namespace, "executor_exit", sid, fence)


def executors_exited(connection: Any, namespace: str, sid: Any, lease: Any) -> bool:
    # ponytail: exact prefix matching is independent of database collation.
    # Retain the native equality for the receipt primary-key lookup, then require
    # exact key equality even with a nondeterministic column collation.
    # If receipt history outgrows the cleanup deadline, add a prefix index.
    rows = connection.execute(
        """SELECT s.response_body, e.response_body AS exited
        FROM control_plane_idempotency_records s LEFT JOIN control_plane_idempotency_records e
          ON e.deployment_namespace=s.deployment_namespace AND e.action='executor_exit'
          AND e.idempotency_key=s.idempotency_key
          AND e.idempotency_key COLLATE "C"=s.idempotency_key
        WHERE s.deployment_namespace=%s AND s.action='executor_started'
          AND starts_with(s.idempotency_key COLLATE "C",%s)""",
        (namespace, f"{sid}:"),
    ).fetchall()
    if any(row["exited"] != row["response_body"] for row in rows):
        return False
    if lease is None:
        return True
    proof = {
        "session_id": str(sid),
        "fence": {
            "control_plane_epoch": str(lease["control_plane_epoch"]),
            "fencing_token": lease["fencing_token"],
            "owner_instance_id": lease["owner_instance_id"],
        },
    }
    # No inference from TTL expiry, terminal text, or a missing registration.
    return any(row["response_body"] == proof for row in rows)


def _receipt(connection: Any, namespace: str, action: str, sid: Any, fence: Any) -> bool:
    row = connection.execute(
        """SELECT response_body FROM control_plane_idempotency_records
        WHERE deployment_namespace=%s AND action=%s AND idempotency_key=%s""",
        (namespace, action, executor_key(sid, fence)),
    ).fetchone()
    return row is not None and row["response_body"] == {
        "session_id": str(sid),
        "fence": fence.model_dump(mode="json"),
    }


def _save(connection: Any, namespace: str, action: str, sid: Any, fence: Any) -> bool:
    key = executor_key(sid, fence)
    row = connection.execute(
        """INSERT INTO control_plane_idempotency_records
        (deployment_namespace,action,idempotency_key,request_hash,status_code,response_body,created_at)
        VALUES (%s,%s,%s,%s,200,%s::jsonb,clock_timestamp())
        ON CONFLICT(deployment_namespace,action,idempotency_key) DO NOTHING RETURNING 1""",
        (
            namespace,
            action,
            key,
            key,
            json.dumps({"session_id": str(sid), "fence": fence.model_dump(mode="json")}),
        ),
    ).fetchone()
    return row is not None
