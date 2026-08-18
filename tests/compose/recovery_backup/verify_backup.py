"""Seed and verify a portable logical PostgreSQL backup."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_storage.postgres import PostgresEventStore, apply_postgres_migrations
from psycopg.rows import dict_row

NAMESPACE = "recovery-backup"
SEED_CREATED_AT = datetime(2026, 8, 5, tzinfo=UTC)


def _schema_snapshot(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    migration_rows = connection.execute(
        """
        SELECT version, name, checksum
        FROM zebra_schema_migrations
        ORDER BY version
        """
    ).fetchall()
    schema_tables = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for table_name in ("session_streams", "session_events"):
        row = connection.execute(
            f"""
            SELECT count(*) AS count
            FROM {table_name}
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"count query returned no row for {table_name}")
        counts[table_name] = int(row["count"])
    return {
        "migration_rows": [
            {
                "version": int(row["version"]),
                "name": row["name"],
                "checksum": row["checksum"],
            }
            for row in migration_rows
        ],
        "schema_tables": [row["table_name"] for row in schema_tables],
        "counts": counts,
    }


def _event_snapshot(event: SessionEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "session_id": str(event.session_id),
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "payload": event.payload,
        "actor": event.actor.value,
        "created_at": event.created_at.isoformat(),
        "idempotency_key": event.idempotency_key,
    }


def _read_snapshot(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return _schema_snapshot(connection)


def _assert_namespace_read(
    dsn: str,
    expected: dict[str, Any],
) -> None:
    session_id = SessionId(UUID(expected["event"]["session_id"]))
    store = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    events = store.read_since(session_id, -1)
    if len(events) != 1 or _event_snapshot(events[0]) != expected["event"]:
        raise RuntimeError("namespace-scoped event read does not match the seed")
    other_namespace = PostgresEventStore(dsn, deployment_namespace="other-namespace")
    if other_namespace.read_since(session_id, -1):
        raise RuntimeError("event read leaked across deployment namespaces")


def _seed(dsn: str, expected_path: Path) -> None:
    apply_postgres_migrations(dsn)
    session_id = new_session_id()
    event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "logical backup portability seed"},
        idempotency_key="recovery-backup-seed-1",
        created_at=SEED_CREATED_AT,
    )
    PostgresEventStore(dsn, deployment_namespace=NAMESPACE).append(event)
    expected = {"event": _event_snapshot(event), "schema": _read_snapshot(dsn)}
    _assert_namespace_read(dsn, expected)
    expected_path.write_text(
        json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        "RECOVERY_BACKUP_SEED=PASS "
        f"migrations={len(expected['schema']['migration_rows'])} "
        f"events={expected['schema']['counts']['session_events']}"
    )


def _verify(dsn: str, expected_path: Path) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual_schema = _read_snapshot(dsn)
    if actual_schema != expected["schema"]:
        raise RuntimeError(
            "restored schema/count snapshot differs from the source snapshot: "
            f"expected={expected['schema']!r} actual={actual_schema!r}"
        )
    _assert_namespace_read(dsn, expected)
    print(
        "RECOVERY_BACKUP_VERIFY=PASS "
        f"migrations={len(actual_schema['migration_rows'])} "
        f"events={actual_schema['counts']['session_events']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--mode", choices=("seed", "verify"), required=True)
    args = parser.parse_args()
    if args.mode == "seed":
        _seed(args.dsn, args.expected)
    else:
        _verify(args.dsn, args.expected)


if __name__ == "__main__":
    main()
