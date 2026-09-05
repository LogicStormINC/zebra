"""Explicit operator backfill and discovery only; neither claims nor executes work."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from agent_core.contracts.broker_envelope import Namespace, PrincipalScope
from agent_core.domain.events import SessionEvent
from psycopg.errors import LockNotAvailable
from pydantic import TypeAdapter, ValidationError

from agent_storage.postgres.command_wakeup import (
    command_scope_key,
    record_command_wakeup_in_transaction,
)
from agent_storage.postgres.database import PostgresDatabase

MAX_BATCH_SIZE = 500


@dataclass(frozen=True)
class BackfillProgress:
    state: str
    high_session_id: UUID | None
    high_sequence: int | None
    cursor_session_id: UUID | None
    cursor_sequence: int | None


@dataclass(frozen=True)
class PendingCursor:
    created_at: datetime
    accepted_event_id: UUID
    scope_sequence: int = 0
    cycle_page: int = 0
    probe_scope_key: str | None = None
    probe_high_scope_key: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.utcoffset() is None
            or not isinstance(self.accepted_event_id, UUID)
            or type(self.scope_sequence) is not int
            or self.scope_sequence < 0
            or type(self.cycle_page) is not int
            or self.cycle_page < 0
            or (self.probe_scope_key is None) != (self.probe_high_scope_key is None)
            or (
                self.probe_scope_key is not None
                and (
                    not isinstance(self.probe_scope_key, str)
                    or not self.probe_scope_key
                    or len(self.probe_scope_key) > 128
                    or not isinstance(self.probe_high_scope_key, str)
                    or self.probe_scope_key > self.probe_high_scope_key
                )
            )
        ):
            raise ValueError("pending cursor requires an aware datetime and UUID")


@dataclass(frozen=True)
class PendingCommand:
    command_id: UUID
    session_id: UUID
    accepted_sequence: int
    cursor: PendingCursor


def _limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_BATCH_SIZE:
        raise ValueError("batch size must be an integer between 1 and 500")


def _progress(row: dict[str, Any]) -> BackfillProgress:
    return BackfillProgress(
        row["backfill_state"],
        row["high_session_id"],
        row["high_sequence"],
        row["cursor_session_id"],
        row["cursor_sequence"],
    )


def _database(dsn: str, namespace: str) -> PostgresDatabase:
    try:
        TypeAdapter(Namespace).validate_python(namespace)
    except ValidationError:
        raise ValueError("invalid command deployment namespace") from None
    return PostgresDatabase(dsn, deployment_namespace=namespace)


def begin_command_backfill(dsn: str, *, deployment_namespace: str) -> BackfillProgress:
    """Enable live admission behind an INSERT barrier and freeze the history boundary.

    Explicit operator action only. The table lock waits at most five seconds.
    Existing initialized progress is never reset, including on retries.
    """
    database = _database(dsn, deployment_namespace)
    try:
        with database.connect() as connection:
            connection.execute("SET LOCAL lock_timeout = '5s'")
            row = connection.execute(
                "SELECT * FROM command_wakeup_rollouts WHERE deployment_namespace = %s",
                (deployment_namespace,),
            ).fetchone()
            if row is not None and row["backfill_state"] != "not_started":
                return _progress(row)
            # ponytail: explicit cutover briefly blocks ALL Event inserts; lock
            # acquisition waits at most 5s. Upgrade to a per-deployment admission
            # lock protocol if operational contention requires finer isolation.
            # Lock order is table then rollout: an in-flight append holds the
            # table INSERT lock before consulting the rollout row.
            connection.execute("LOCK TABLE session_events IN SHARE MODE")
            connection.execute(
                """INSERT INTO command_wakeup_rollouts (deployment_namespace)
                   VALUES (%s) ON CONFLICT DO NOTHING""",
                (deployment_namespace,),
            )
            row = connection.execute(
                """SELECT * FROM command_wakeup_rollouts
                   WHERE deployment_namespace = %s FOR UPDATE""",
                (deployment_namespace,),
            ).fetchone()
            assert row is not None
            if row["backfill_state"] != "not_started":
                return _progress(row)
            high = connection.execute(
                """SELECT session_id, sequence FROM session_events
                   WHERE deployment_namespace = %s AND event_type = 'session_command_accepted'
                   ORDER BY session_id DESC, sequence DESC LIMIT 1""",
                (deployment_namespace,),
            ).fetchone()
            row = connection.execute(
                """UPDATE command_wakeup_rollouts SET admission_enabled = TRUE,
                   backfill_state = %s, high_session_id = %s, high_sequence = %s
                   WHERE deployment_namespace = %s RETURNING *""",
                (
                    "complete" if high is None else "running",
                    None if high is None else high["session_id"],
                    None if high is None else high["sequence"],
                    deployment_namespace,
                ),
            ).fetchone()
            assert row is not None
            return _progress(row)
    except LockNotAvailable:
        raise ValueError("command backfill cutover lock timed out; retry explicitly") from None


def backfill_command_batch(
    dsn: str, *, deployment_namespace: str, batch_size: int = 100
) -> BackfillProgress:
    _limit(batch_size)
    with _database(dsn, deployment_namespace).connect() as connection:
        row = connection.execute(
            """SELECT * FROM command_wakeup_rollouts
               WHERE deployment_namespace = %s FOR UPDATE""",
            (deployment_namespace,),
        ).fetchone()
        if row is None or row["backfill_state"] == "not_started" or not row["admission_enabled"]:
            raise ValueError("command backfill requires explicit active cutover")
        if row["backfill_state"] == "complete":
            return _progress(row)
        rows = connection.execute(
            """SELECT event_id, session_id, sequence, event_type, payload, actor,
                      created_at, causation_id, correlation_id, idempotency_key,
                      policy_version, model_profile
               FROM session_events WHERE deployment_namespace = %s
                 AND event_type = 'session_command_accepted'
                 AND (session_id, sequence) <= (%s, %s)
                 AND (%s::uuid IS NULL OR (session_id, sequence) > (%s, %s))
               ORDER BY session_id, sequence LIMIT %s""",
            (
                deployment_namespace,
                row["high_session_id"],
                row["high_sequence"],
                row["cursor_session_id"],
                row["cursor_session_id"],
                row["cursor_sequence"],
                batch_size,
            ),
        ).fetchall()
        for event in rows:
            record_command_wakeup_in_transaction(
                connection, deployment_namespace, SessionEvent.model_validate(event)
            )
        last = rows[-1] if rows else None
        complete = len(rows) < batch_size or (
            last is not None
            and (last["session_id"], last["sequence"])
            == (row["high_session_id"], row["high_sequence"])
        )
        updated = connection.execute(
            """UPDATE command_wakeup_rollouts SET backfill_state = %s,
               cursor_session_id = %s, cursor_sequence = %s
               WHERE deployment_namespace = %s RETURNING *""",
            (
                "complete" if complete else "running",
                last["session_id"] if last else row["cursor_session_id"],
                last["sequence"] if last else row["cursor_sequence"],
                deployment_namespace,
            ),
        ).fetchone()
        assert updated is not None
        return _progress(updated)


def discover_pending_commands(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    batch_size: int = 100,
    after: PendingCursor | None = None,
) -> tuple[PendingCommand, ...]:
    """Discover derived candidates; consumers MUST reconcile canonical receipts/state."""
    _limit(batch_size)
    if not isinstance(scope, PrincipalScope):
        raise ValueError("pending discovery requires a PrincipalScope")
    if after is not None and not isinstance(after, PendingCursor):
        raise ValueError("invalid pending discovery cursor")
    with _database(dsn, deployment_namespace).connect() as connection:
        rows = connection.execute(
            """SELECT command_id, session_id, accepted_sequence, created_at, accepted_event_id
               FROM session_command_pending WHERE deployment_namespace = %s
                 AND scope_key = %s AND status = 'pending'
                 AND (%s::timestamptz IS NULL OR (created_at, accepted_event_id) > (%s, %s))
               ORDER BY created_at, accepted_event_id LIMIT %s""",
            (
                deployment_namespace,
                command_scope_key(scope),
                after.created_at if after else None,
                after.created_at if after else None,
                after.accepted_event_id if after else None,
                batch_size,
            ),
        ).fetchall()
    return tuple(
        PendingCommand(
            row["command_id"],
            row["session_id"],
            row["accepted_sequence"],
            PendingCursor(row["created_at"], row["accepted_event_id"]),
        )
        for row in rows
    )
