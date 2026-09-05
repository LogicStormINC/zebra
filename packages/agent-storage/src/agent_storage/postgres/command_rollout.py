"""Default-off command delivery rollout authority and durable audit."""

from typing import Any, Literal
from uuid import UUID

from agent_storage.postgres.command_wakeup_discovery import _database

RolloutMode = Literal["broker", "shadow"]
ScopeDeliveryDisposition = Literal["broker", "fallback_pending", "fallback_settled"]


def rollout_text(value: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= maximum
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
    ):
        raise ValueError("invalid rollout audit text")
    return value


def rollout_scope_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("invalid rollout scope key")
    return value


def set_command_scope_rollout(
    dsn: str,
    *,
    deployment_namespace: str,
    scope_key: str,
    mode: RolloutMode | None,
    actor: str,
    reason: str,
) -> None:
    """Change one opaque scope and append an immutable audit record."""
    key = rollout_scope_key(scope_key)
    actor, reason = rollout_text(actor, maximum=128), rollout_text(reason, maximum=512)
    if mode not in (None, "broker", "shadow"):
        raise ValueError("invalid command rollout mode")
    with _database(dsn, deployment_namespace).connect() as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,50))",
            (f"{deployment_namespace}:command-rollout:{key}",),
        )
        current = connection.execute(
            """SELECT mode FROM command_delivery_scope_rollouts
               WHERE deployment_namespace=%s AND scope_key=%s FOR UPDATE""",
            (deployment_namespace, key),
        ).fetchone()
        previous_mode = None if current is None else current["mode"]
        if previous_mode == mode:
            return
        if mode is None:
            connection.execute(
                """DELETE FROM command_delivery_scope_rollouts
                   WHERE deployment_namespace=%s AND scope_key=%s""",
                (deployment_namespace, key),
            )
        else:
            connection.execute(
                """INSERT INTO command_delivery_scope_rollouts
                   (deployment_namespace,scope_key,mode,actor,reason)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (deployment_namespace,scope_key) DO UPDATE
                   SET mode=EXCLUDED.mode, actor=EXCLUDED.actor, reason=EXCLUDED.reason,
                       updated_at=clock_timestamp()""",
                (deployment_namespace, key, mode, actor, reason),
            )
        connection.execute(
            """INSERT INTO command_delivery_scope_rollout_audit
               (deployment_namespace,scope_key,previous_mode,new_mode,actor,reason)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (deployment_namespace, key, previous_mode, mode, actor, reason),
        )


def command_scope_mode(connection: Any, namespace: str, scope_key: str) -> str:
    row = connection.execute(
        """SELECT mode FROM command_delivery_scope_rollouts
           WHERE deployment_namespace=%s AND scope_key=%s""",
        (namespace, rollout_scope_key(scope_key)),
    ).fetchone()
    return "fallback" if row is None else row["mode"]


def get_command_scope_mode(dsn: str, *, deployment_namespace: str, scope_key: str) -> str:
    with _database(dsn, deployment_namespace).connect() as connection:
        return command_scope_mode(connection, deployment_namespace, scope_key)


def command_delivery_disposition(
    dsn: str,
    *,
    deployment_namespace: str,
    scope_key: str,
    accepted_event_id: UUID,
) -> ScopeDeliveryDisposition:
    """Tell a stale broker hint whether fallback still owns pending work."""
    key = rollout_scope_key(scope_key)
    with _database(dsn, deployment_namespace).connect() as connection:
        mode = command_scope_mode(connection, deployment_namespace, key)
        if mode == "broker":
            return "broker"
        pending = connection.execute(
            """SELECT status,scope_key FROM session_command_pending
               WHERE deployment_namespace=%s AND accepted_event_id=%s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        if pending is None or pending["scope_key"] != key:
            raise ValueError("command rollout scope reconciliation failed")
        return "fallback_pending" if pending["status"] == "pending" else "fallback_settled"
