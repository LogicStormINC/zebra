"""Explicit operator-only historical retirement. No Event or execution mutation."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agent_core.application import current_turn
from agent_core.application.session_projection import rebuild_session
from agent_core.application.turn_projection import project_turns
from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.turns import TurnStatus
from psycopg.errors import LockNotAvailable

from agent_storage.postgres.command_wakeup import _scope_from_binding, command_scope_key
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.leases import _lock_epoch
from agent_storage.postgres.projections import get_session_in_transaction
from agent_storage.postgres.task_index_transactions import _lock_task


@dataclass(frozen=True)
class RetirementPreview:
    task_id: UUID
    session_id: UUID
    expected_revision: int
    closure_event_id: UUID
    accepted_event_ids: tuple[UUID, ...]
    high_session_id: UUID
    high_sequence: int


def preview_command_retirement(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    task_id: UUID,
    session_id: UUID,
) -> RetirementPreview:
    """Read-only consistent eligibility snapshot; apply must revalidate under locks."""
    _identity(scope, task_id, session_id)
    with _database(dsn, deployment_namespace).connect() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        preview, _ = _eligible(connection, deployment_namespace, scope, task_id, session_id)
        return preview


def retire_historical_commands(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    task_id: UUID,
    session_id: UUID,
    expected_revision: int,
    closure_event_id: UUID,
    accepted_event_ids: tuple[UUID, ...],
    operator_id: str,
    reason: str,
    operation_key: str,
) -> RetirementPreview:
    """Atomically audit an exact historical set; duplicate keys never change the audit."""
    _identity(scope, task_id, session_id)
    if (
        type(expected_revision) is not int
        or expected_revision < 1
        or not isinstance(closure_event_id, UUID)
        or type(accepted_event_ids) is not tuple
        or not 1 <= len(accepted_event_ids) <= 500
        or any(not isinstance(value, UUID) for value in accepted_event_ids)
        or len(set(accepted_event_ids)) != len(accepted_event_ids)
    ):
        raise ValueError("invalid exact command retirement boundary")
    for value, limit in ((operator_id, 128), (operation_key, 128), (reason, 1000)):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > limit
            or any(not char.isprintable() for char in value)
        ):
            raise ValueError("invalid retirement audit metadata")
    namespace = deployment_namespace
    identity = dict(
        scope_key=command_scope_key(scope),
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        task_id=task_id,
        session_id=session_id,
        expected_revision=expected_revision,
        closure_event_id=closure_event_id,
        operator_id=operator_id,
        reason=reason,
    )
    with _database(dsn, namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout = '5s'")
        boundary = connection.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS acquired",
            (f"{namespace}:{session_id}",),
        ).fetchone()
        if boundary is None or not boundary["acquired"]:
            raise ValueError("retirement boundary is busy; retry explicitly")
        previous = connection.execute(
            """SELECT * FROM command_retirement_operations
               WHERE deployment_namespace=%s AND operation_key=%s""",
            (namespace, operation_key),
        ).fetchone()
        if previous is not None:
            rows = connection.execute(
                """SELECT accepted_event_id FROM command_retirements
                   WHERE deployment_namespace=%s AND operation_key=%s ORDER BY accepted_sequence""",
                (namespace, operation_key),
            ).fetchall()
            ids = tuple(row["accepted_event_id"] for row in rows)
            if any(previous[key] != value for key, value in identity.items()) or set(ids) != set(
                accepted_event_ids
            ):
                raise ValueError("retirement operation identity conflict")
            return RetirementPreview(
                task_id,
                session_id,
                expected_revision,
                closure_event_id,
                ids,
                previous["high_session_id"],
                previous["high_sequence"],
            )
        _lock_epoch(connection, namespace)
        # Root Task and Session advisory keys coincide. Never wait for a lease
        # holder that may need that Task key for fenced rollover (lease -> Task).
        try:
            connection.execute(
                """SELECT session_id FROM worker_leases WHERE deployment_namespace=%s
                   AND session_id=%s FOR UPDATE NOWAIT""",
                (namespace, session_id),
            ).fetchone()
        except LockNotAvailable:
            raise ValueError("retirement lease is busy; retry explicitly") from None
        connection.execute(
            """SELECT current_version FROM session_streams WHERE deployment_namespace=%s
               AND session_id=%s FOR UPDATE""",
            (namespace, session_id),
        ).fetchone()
        # Match fenced rollover: lease -> stream -> Task advisory/row, never Task first.
        _lock_task(connection, namespace, TaskId(task_id))
        connection.execute(
            """SELECT task_id FROM agent_tasks WHERE deployment_namespace=%s AND task_id=%s
               FOR UPDATE""",
            (namespace, task_id),
        ).fetchone()
        preview, candidates = _eligible(connection, namespace, scope, task_id, session_id)
        if (
            preview.expected_revision != expected_revision
            or preview.closure_event_id != closure_event_id
            or set(preview.accepted_event_ids) != set(accepted_event_ids)
        ):
            raise ValueError("retirement preview is stale or command set is incomplete")
        connection.execute(
            """INSERT INTO command_retirement_operations (deployment_namespace, operation_key,
               scope_key, tenant_id, workspace_id, task_id, session_id, expected_revision,
               closure_event_id, operator_id, reason, high_session_id, high_sequence)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                namespace,
                operation_key,
                *identity.values(),
                preview.high_session_id,
                preview.high_sequence,
            ),
        )
        for row in candidates:
            connection.execute(
                """INSERT INTO command_retirements (deployment_namespace, accepted_event_id,
                   operation_key, scope_key, session_id, command_id, accepted_sequence)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    namespace,
                    row["accepted_event_id"],
                    operation_key,
                    identity["scope_key"],
                    session_id,
                    row["command_id"],
                    row["accepted_sequence"],
                ),
            )
            connection.execute(
                """UPDATE session_command_pending SET status='cancelled'
                   WHERE deployment_namespace=%s AND accepted_event_id=%s""",
                (namespace, row["accepted_event_id"]),
            )
        return preview


def _identity(scope: PrincipalScope, task_id: UUID, session_id: UUID) -> None:
    if not isinstance(scope, PrincipalScope) or not all(
        isinstance(value, UUID) for value in (task_id, session_id)
    ):
        raise ValueError("retirement requires trusted scope and Task/Session UUIDs")


def _eligible(
    connection: Any,
    namespace: str,
    scope: PrincipalScope,
    task_id: UUID,
    session_id: UUID,
) -> tuple[RetirementPreview, list[dict[str, Any]]]:
    task = connection.execute(
        """SELECT task.active_segment_id FROM agent_tasks AS task
           JOIN execution_segments AS segment
             ON segment.deployment_namespace=task.deployment_namespace
            AND segment.task_id=task.task_id AND segment.session_id=task.active_segment_id
           WHERE task.deployment_namespace=%s AND task.task_id=%s""",
        (namespace, task_id),
    ).fetchone()
    if task is None or task["active_segment_id"] != session_id:
        raise ValueError("retirement requires the active Task Session")
    lease = connection.execute(
        """SELECT 1 FROM worker_leases WHERE deployment_namespace=%s AND session_id=%s
           AND released_at IS NULL""",
        (namespace, session_id),
    ).fetchone()
    if lease is not None:
        raise ValueError("retirement requires no unreleased lease")
    # ponytail: existing Core Turn replay is O(session history). Never truncate
    # correctness; replace with a proven canonical Turn index before large-history operation.
    rows = connection.execute(
        """SELECT event_id, session_id, sequence, event_type, payload, actor, created_at,
           causation_id, correlation_id, idempotency_key, policy_version, model_profile
           FROM session_events WHERE deployment_namespace=%s AND session_id=%s ORDER BY sequence""",
        (namespace, session_id),
    ).fetchall()
    events = [SessionEvent.model_validate(row) for row in rows]
    stream = connection.execute(
        """SELECT current_version FROM session_streams
           WHERE deployment_namespace=%s AND session_id=%s""",
        (namespace, session_id),
    ).fetchone()
    if stream is None or not events or stream["current_version"] != events[-1].sequence:
        raise ValueError("retirement requires a matching canonical stream head")
    if not events or _scope_from_binding(connection, namespace, events[0]) != scope:
        raise ValueError("retirement binding scope mismatch")
    rebuilt = rebuild_session(events)
    stored = get_session_in_transaction(connection, namespace, SessionId(session_id))
    if stored != rebuilt:
        raise ValueError("retirement requires a matching canonical Session projection")
    if rebuilt.status is not SessionStatus.AWAITING_TURN or current_turn(events):
        raise ValueError("retirement requires a quiescent conversation Turn")
    turns = project_turns(events)
    if (
        not turns
        or turns[-1].legacy
        or turns[-1].status is not TurnStatus.COMPLETED
        or (turns[-1].closes_segment is not False)
    ):
        raise ValueError("retirement requires a real non-closing completed Turn")
    closure = next(event for event in events if event.sequence == turns[-1].closed_sequence)
    if closure.event_type is not EventType.TURN_COMPLETED or any(
        event.event_type is not EventType.SESSION_TITLE_UPDATED
        for event in events
        if event.sequence > closure.sequence
    ):
        raise ValueError("retirement has an unsafe post-closure tail")
    rollout = connection.execute(
        "SELECT * FROM command_wakeup_rollouts WHERE deployment_namespace=%s",
        (namespace,),
    ).fetchone()
    if (
        rollout is None
        or not rollout["admission_enabled"]
        or rollout["backfill_state"] != "complete"
        or rollout["high_session_id"] is None
    ):
        raise ValueError("retirement requires a completed explicit backfill")
    candidates = connection.execute(
        """SELECT event.event_id AS canonical_id, event.sequence AS canonical_sequence,
           event.payload, pending.* FROM session_events AS event
           LEFT JOIN session_command_pending AS pending
             ON pending.deployment_namespace=event.deployment_namespace
            AND pending.accepted_event_id=event.event_id
           WHERE event.deployment_namespace=%s AND event.session_id=%s
             AND event.event_type='session_command_accepted'
             AND NOT EXISTS (SELECT 1 FROM command_handoff_receipts AS receipt
                 WHERE receipt.deployment_namespace=event.deployment_namespace
                   AND receipt.accepted_event_id=event.event_id AND receipt.scope_key=%s
                   AND receipt.status='accepted' AND receipt.handled_event_id IS NOT NULL)
             AND NOT EXISTS (SELECT 1 FROM command_control_receipts AS control
                 WHERE control.deployment_namespace=event.deployment_namespace
                   AND control.accepted_event_id=event.event_id AND control.scope_key=%s
                   AND control.kind='suspend' AND control.outcome='unsupported')
             AND NOT EXISTS (SELECT 1 FROM command_retirements AS retired
                 WHERE retired.deployment_namespace=event.deployment_namespace
                   AND retired.accepted_event_id=event.event_id AND retired.scope_key=%s)
           ORDER BY event.sequence LIMIT 501""",
        (namespace, session_id, *(command_scope_key(scope),) * 3),
    ).fetchall()
    if not 1 <= len(candidates) <= 500:
        raise ValueError("retirement requires between one and 500 exact historical commands")
    for row in candidates:
        if (
            row["origin"] != "historical"
            or row["status"] != "pending"
            or row["scope_key"] != command_scope_key(scope)
            or row["tenant_id"] != scope.tenant_id
            or row["workspace_id"] != scope.workspace_id
            or row["session_id"] != session_id
            or row["accepted_event_id"] != row["canonical_id"]
            or row["accepted_sequence"] != row["canonical_sequence"]
            or str(row["command_id"]) != row["payload"]["command_id"]
            or (session_id, row["accepted_sequence"])
            > (rollout["high_session_id"], rollout["high_sequence"])
        ):
            raise ValueError("retirement candidate is not exact historical backfill")
        receipt = connection.execute(
            """SELECT 1 FROM command_handoff_receipts WHERE deployment_namespace=%s
               AND accepted_event_id=%s UNION ALL SELECT 1 FROM command_control_receipts
               WHERE deployment_namespace=%s AND accepted_event_id=%s LIMIT 1""",
            (namespace, row["accepted_event_id"], namespace, row["accepted_event_id"]),
        ).fetchone()
        if receipt is not None:
            raise ValueError("retirement cannot replace an existing command receipt")
    return RetirementPreview(
        task_id,
        session_id,
        events[-1].sequence,
        closure.event_id,
        tuple(row["accepted_event_id"] for row in candidates),
        rollout["high_session_id"],
        rollout["high_sequence"],
    ), candidates
