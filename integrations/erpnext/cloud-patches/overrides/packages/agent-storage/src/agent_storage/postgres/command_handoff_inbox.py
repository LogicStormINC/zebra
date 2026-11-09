from typing import Any


def _check_inbox(
    connection: Any,
    namespace: str,
    pending: dict[str, Any],
    outbox: dict[str, Any],
) -> str | None:
    row = connection.execute(
        """SELECT * FROM broker_command_inbox
           WHERE deployment_namespace = %s AND message_id = %s""",
        (namespace, outbox["message_id"]),
    ).fetchone()
    if row is not None and (
        row["envelope_digest"] != outbox["envelope_digest"]
        or row["scope_key"] != pending["scope_key"]
        or row["command_id"] != pending["command_id"]
        or row["accepted_event_id"] != pending["accepted_event_id"]
    ):
        raise ValueError("command Inbox identity or digest conflict")
    return None if row is None else str(row["status"])


def _inbox(
    connection: Any,
    namespace: str,
    pending: dict[str, Any],
    outbox: dict[str, Any],
    status: str,
) -> None:
    connection.execute(
        """INSERT INTO broker_command_inbox (
            deployment_namespace, message_id, envelope_digest, scope_key,
            command_id, accepted_event_id, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (
            namespace,
            outbox["message_id"],
            outbox["envelope_digest"],
            pending["scope_key"],
            pending["command_id"],
            pending["accepted_event_id"],
            status,
        ),
    )
    if _check_inbox(connection, namespace, pending, outbox) != status:
        raise ValueError("command Inbox and receipt status conflict")
