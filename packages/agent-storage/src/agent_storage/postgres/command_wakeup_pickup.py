"""Bounded deployment-wide pending hints; authority comes from frozen binding."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.contracts.session_commands import SessionCommandKind
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId
from psycopg import sql

from agent_storage.postgres.command_wakeup import _scope_from_binding, command_scope_key
from agent_storage.postgres.command_wakeup_discovery import PendingCursor, _database, _limit
from agent_storage.postgres.events import read_event_in_transaction

PickupLane = Literal["execution", "control"]
PickupScopeMode = Literal["all", "broker", "fallback"]
CONTROL_KINDS = frozenset(
    {SessionCommandKind.CANCEL, SessionCommandKind.STOP, SessionCommandKind.SUSPEND}
)
MAX_FAIR_CURSOR_PAGES = 16


@dataclass(frozen=True)
class CommandPickup:
    accepted_event_id: UUID
    cursor: PendingCursor


@dataclass(frozen=True)
class ResolvedCommand:
    accepted_event_id: UUID
    scope: PrincipalScope
    kind: SessionCommandKind


def discover_command_pickups(
    dsn: str,
    *,
    deployment_namespace: str,
    lane: PickupLane,
    batch_size: int = 16,
    after: PendingCursor | None = None,
    scope_mode: PickupScopeMode = "all",
) -> tuple[CommandPickup, ...]:
    """Keyset page with bounded prefix probes that never discard forward progress."""
    _limit(batch_size)
    if (
        lane not in ("execution", "control")
        or scope_mode
        not in (
            "all",
            "broker",
            "fallback",
        )
        or (after is not None and not isinstance(after, PendingCursor))
    ):
        raise ValueError("invalid pickup lane or cursor")
    kinds = "('cancel','stop','suspend')" if lane == "control" else "('run','resume','message')"
    scope_filter = {
        "all": sql.SQL(""),
        "broker": sql.SQL(
            """AND EXISTS (SELECT 1 FROM command_delivery_scope_rollouts rollout
               WHERE rollout.deployment_namespace=session_command_pending.deployment_namespace
                 AND rollout.scope_key=session_command_pending.scope_key
                 AND rollout.mode='broker')"""
        ),
        "fallback": sql.SQL(
            """AND NOT EXISTS (SELECT 1 FROM command_delivery_scope_rollouts rollout
               WHERE rollout.deployment_namespace=session_command_pending.deployment_namespace
                 AND rollout.scope_key=session_command_pending.scope_key
                 AND rollout.mode='broker')"""
        ),
    }[scope_mode]
    probing = after is not None and after.cycle_page >= MAX_FAIR_CURSOR_PAGES

    def fetch(
        connection: Any,
        sequence: int | None,
        created_at: datetime | None,
        event_id: UUID | None,
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            connection.execute(
                sql.SQL(
                    """SELECT accepted_event_id,created_at,scope_sequence
                   FROM session_command_pending
                   WHERE deployment_namespace=%s AND status='pending' AND command_kind IN {} {}
                     AND (%s::bigint IS NULL OR
                        (scope_sequence,created_at,accepted_event_id)>(%s,%s,%s))
                 ORDER BY scope_sequence,created_at,accepted_event_id LIMIT %s"""
                ).format(sql.SQL(kinds), scope_filter),
                (
                    deployment_namespace,
                    sequence,
                    sequence,
                    created_at,
                    event_id,
                    batch_size,
                ),
            ).fetchall(),
        )

    with _database(dsn, deployment_namespace).connect() as connection:
        if probing:
            assert after is not None
            probe_after = after.probe_scope_key
            probe_high = after.probe_high_scope_key
            if probe_high is None:
                high_row = connection.execute(
                    sql.SQL(
                        """SELECT max(scope_key) AS value FROM session_command_pending
                           WHERE deployment_namespace=%s AND status='pending'
                             AND command_kind IN {} {}"""
                    ).format(sql.SQL(kinds), scope_filter),
                    (deployment_namespace,),
                ).fetchone()
                assert high_row is not None
                probe_high = high_row["value"]
            rows = (
                []
                if probe_high is None
                else connection.execute(
                    sql.SQL(
                        """SELECT DISTINCT ON (scope_key)
                                  scope_key,accepted_event_id,created_at,scope_sequence
                           FROM session_command_pending
                           WHERE deployment_namespace=%s AND status='pending'
                             AND command_kind IN {} {}
                             AND (%s::text IS NULL OR scope_key>%s) AND scope_key<=%s
                           ORDER BY scope_key,scope_sequence,created_at,accepted_event_id
                           LIMIT %s"""
                    ).format(sql.SQL(kinds), scope_filter),
                    (
                        deployment_namespace,
                        probe_after,
                        probe_after,
                        probe_high,
                        batch_size,
                    ),
                ).fetchall()
            )
            if not rows and probe_after is not None:
                probe_after = None
                high_row = connection.execute(
                    sql.SQL(
                        """SELECT max(scope_key) AS value FROM session_command_pending
                           WHERE deployment_namespace=%s AND status='pending'
                             AND command_kind IN {} {}"""
                    ).format(sql.SQL(kinds), scope_filter),
                    (deployment_namespace,),
                ).fetchone()
                assert high_row is not None
                probe_high = high_row["value"]
                rows = (
                    []
                    if probe_high is None
                    else connection.execute(
                        sql.SQL(
                            """SELECT DISTINCT ON (scope_key)
                                      scope_key,accepted_event_id,created_at,scope_sequence
                               FROM session_command_pending
                               WHERE deployment_namespace=%s AND status='pending'
                                 AND command_kind IN {} {} AND scope_key<=%s
                               ORDER BY scope_key,scope_sequence,created_at,accepted_event_id
                               LIMIT %s"""
                        ).format(sql.SQL(kinds), scope_filter),
                        (deployment_namespace, probe_high, batch_size),
                    ).fetchall()
                )
        else:
            rows = fetch(
                connection,
                after.scope_sequence if after is not None else None,
                after.created_at if after is not None else None,
                after.accepted_event_id if after is not None else None,
            )

    pickups = []
    for row in rows:
        if probing:
            assert after is not None
            last_in_ring = row["scope_key"] == probe_high
            cursor = PendingCursor(
                after.created_at,
                after.accepted_event_id,
                after.scope_sequence,
                0,
                None if last_in_ring else row["scope_key"],
                None if last_in_ring else probe_high,
            )
        else:
            cursor = PendingCursor(
                row["created_at"],
                row["accepted_event_id"],
                row["scope_sequence"],
                1 if after is None else after.cycle_page + 1,
                None if after is None else after.probe_scope_key,
                None if after is None else after.probe_high_scope_key,
            )
        pickups.append(CommandPickup(row["accepted_event_id"], cursor))
    return tuple(pickups)


def resolve_command_pickup(
    dsn: str,
    *,
    deployment_namespace: str,
    accepted_event_id: UUID,
) -> ResolvedCommand:
    """The untrusted UUID is only a lookup hint within configured deployment."""
    if not isinstance(accepted_event_id, UUID):
        raise ValueError("invalid command lookup hint")
    with _database(dsn, deployment_namespace).connect() as connection:
        event = read_event_in_transaction(
            connection, deployment_namespace, EventId(accepted_event_id)
        )
        if event is None or event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
            raise ValueError("missing canonical accepted command")
        scope = _scope_from_binding(connection, deployment_namespace, event)
        pending = connection.execute(
            """SELECT * FROM session_command_pending WHERE deployment_namespace=%s
               AND accepted_event_id=%s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        kind = SessionCommandKind(event.payload["kind"])
        if (
            pending is None
            or pending["scope_key"] != command_scope_key(scope)
            or pending["tenant_id"] != scope.tenant_id
            or pending["workspace_id"] != scope.workspace_id
            or pending["session_id"] != event.session_id
            or pending["accepted_sequence"] != event.sequence
            or str(pending["command_id"]) != event.payload["command_id"]
            or pending["command_kind"] != kind.value
        ):
            raise ValueError("pending pickup differs from canonical identity or kind")
    return ResolvedCommand(accepted_event_id, scope, kind)
