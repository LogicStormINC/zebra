"""Durable-plane verification helpers for the effect default E2E gate."""

from __future__ import annotations

import json
import os
import sys
import uuid

from agent_storage.postgres.epoch import bootstrap_control_plane_epoch
from agent_storage.postgres_composition import postgres_control_plane_stores
from agent_storage.runtime_composition import cloud_composition_from_environment


def _connect():
    import psycopg

    return psycopg.connect(os.environ["ZEBRA_DATABASE_URL"])


def bootstrap_epoch() -> int:
    epoch = bootstrap_control_plane_epoch(
        os.environ["ZEBRA_DATABASE_URL"],
        deployment_namespace=os.environ["ZEBRA_DEPLOYMENT_NAMESPACE"],
    )
    print(json.dumps({"epoch": str(epoch)}))
    return 0


def effect_outbox_count() -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM effect_outbox")
        (count,) = cursor.fetchone()
    print(json.dumps({"effect_outbox_rows": count}))
    return 0


def session_status(session_id: str) -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM session_projections WHERE session_id = %s",
            (session_id,),
        )
        row = cursor.fetchone()
    print(json.dumps({"status": row[0] if row else None}))
    return 0


def event_types(session_id: str) -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT event_type, count(*) FROM session_events"
            " WHERE session_id = %s GROUP BY event_type ORDER BY event_type",
            (uuid.UUID(session_id),),
        )
        rows = cursor.fetchall()
    print(json.dumps({"event_types": [[row[0], row[1]] for row in rows]}))
    return 0


def lease_rows() -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*), count(DISTINCT control_plane_epoch) FROM worker_leases",
        )
        rows_total, epochs = cursor.fetchone()
    print(json.dumps({"lease_rows": rows_total, "lease_epochs": epochs}))
    return 0


def current_revision(session_id: str) -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT coalesce(max(sequence), -1) FROM session_events WHERE session_id = %s",
            (uuid.UUID(session_id),),
        )
        (revision,) = cursor.fetchone()
    print(json.dumps({"current_revision": revision}))
    return 0


def effect_summary() -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, count(*),"
            " count(*) FILTER (WHERE claim_fencing_token IS NOT NULL),"
            " count(*) FILTER (WHERE terminal_event_id IS NOT NULL),"
            " count(*) FILTER (WHERE payload_artifact_ref IS NOT NULL)"
            " FROM effect_outbox GROUP BY status"
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT lifecycle_status, count(*) FROM artifact_payload_metadata"
            " GROUP BY lifecycle_status"
        )
        artifacts = cursor.fetchall()
        cursor.execute("SELECT count(*) FROM governed_memory_operations")
        (memory_ops,) = cursor.fetchone()
    print(
        json.dumps(
            {
                "effects": [
                    {
                        "status": row[0],
                        "rows": row[1],
                        "fenced": row[2],
                        "terminal_bound": row[3],
                        "payload_bound": row[4],
                    }
                    for row in rows
                ],
                "artifacts": [[row[0], row[1]] for row in artifacts],
                "memory_operations": memory_ops,
            }
        )
    )
    return 0


def expire_lease(session_id: str) -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE worker_leases SET acquired_at = now() - interval '15 seconds',"
            " heartbeat_at = now() - interval '10 seconds',"
            " expires_at = now() - interval '5 seconds'"
            " WHERE session_id = %s",
            (uuid.UUID(session_id),),
        )
        (updated,) = (cursor.rowcount,)
    connection.commit()
    print(json.dumps({"expired_leases": updated[0]}))
    return 0


def tool_events(session_id: str) -> int:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT sequence, event_type, payload FROM session_events"
            " WHERE session_id = %s"
            " AND (event_type LIKE 'tool%%' OR event_type LIKE 'tests%%'"
            " OR event_type LIKE 'session_%%')"
            " ORDER BY sequence",
            (uuid.UUID(session_id),),
        )
        rows = cursor.fetchall()
    print(
        json.dumps(
            {
                "events": [
                    {
                        "sequence": row[0],
                        "type": row[1],
                        "status": row[2].get("status"),
                        "output": str(row[2].get("output", ""))[:240],
                    }
                    for row in rows
                ]
            }
        )
    )
    return 0


def rotate_epoch() -> int:
    from agent_storage.postgres.epoch import rotate_control_plane_epoch

    epoch = rotate_control_plane_epoch(
        os.environ["ZEBRA_DATABASE_URL"],
        deployment_namespace=os.environ["ZEBRA_DEPLOYMENT_NAMESPACE"],
    )
    print(json.dumps({"rotated_epoch": str(epoch)}))
    return 0


def handoff_read(session_id: str) -> int:
    cloud = cloud_composition_from_environment()
    stores = postgres_control_plane_stores(
        cloud.dsn,
        deployment_namespace=cloud.deployment_namespace,
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    effects = stores.effects
    terminal = effects.terminal_keys(uuid.UUID(session_id))
    uncertain = effects.has_uncertain(uuid.UUID(session_id))
    print(
        json.dumps(
            {
                "terminal_keys": sorted(str(key) for key in terminal),
                "has_uncertain": uncertain,
            }
        )
    )
    return 0


COMMANDS = {
    "bootstrap-epoch": bootstrap_epoch,
    "effect-outbox-count": effect_outbox_count,
    "effect-summary": effect_summary,
    "session-status": session_status,
    "event-types": event_types,
    "current-revision": current_revision,
    "lease-rows": lease_rows,
    "handoff-read": handoff_read,
    "expire-lease": expire_lease,
    "tool-events": tool_events,
    "rotate-epoch": rotate_epoch,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(f"usage: verify_durable.py {{{'|'.join(COMMANDS)}}} [session_id]", file=sys.stderr)
        return 64
    command = COMMANDS[argv[1]]
    if argv[1] == "current-revision" and len(argv) < 3:
        print("current-revision requires a session id", file=sys.stderr)
        return 64
    if argv[1] == "tool-events" and len(argv) < 3:
        print("tool-events requires a session id", file=sys.stderr)
        return 64
    if argv[1] == "expire-lease" and len(argv) < 3:
        print("expire-lease requires a session id", file=sys.stderr)
        return 64
    if argv[1] == "session-status" and len(argv) < 3:
        print("session-status requires a session id", file=sys.stderr)
        return 64
    if argv[1] == "event-types" and len(argv) < 3:
        print("event-types requires a session id", file=sys.stderr)
        return 64
    if argv[1] == "handoff-read" and len(argv) < 3:
        print("handoff-read requires a session id", file=sys.stderr)
        return 64
    if argv[1] in {
        "session-status",
        "event-types",
        "handoff-read",
        "current-revision",
        "expire-lease",
        "tool-events",
    }:
        return command(argv[2])
    return command()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
