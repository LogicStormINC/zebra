"""Queries used by bounded Effect reconciliation passes."""

from typing import Any

from agent_core.domain.effect_dispatch import EffectDispatch
from agent_core.domain.identifiers import SessionId
from psycopg import Connection

from agent_storage.postgres.effects import effect_dispatch_from_row


def list_uncertain_effects(
    connection: Connection[dict[str, Any]],
    deployment_namespace: str,
    execution_session_id: SessionId,
    limit: int,
) -> tuple[EffectDispatch, ...]:
    if limit < 1 or limit > 1000:
        raise ValueError("reconciliation limit must be between 1 and 1000")
    rows = connection.execute(
        """
        SELECT * FROM effect_outbox
        WHERE deployment_namespace = %s AND execution_session_id = %s
          AND status = 'uncertain'
        ORDER BY updated_at, dispatch_id
        LIMIT %s
        """,
        (deployment_namespace, execution_session_id, limit),
    ).fetchall()
    return tuple(effect_dispatch_from_row(row) for row in rows)
