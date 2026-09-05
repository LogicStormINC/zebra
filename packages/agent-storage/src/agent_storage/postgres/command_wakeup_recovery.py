"""Explicit bounded storage recovery; never recover an uncertain executing program."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.contracts.session_commands import SessionCommandKind
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from psycopg.types.json import Jsonb

from agent_storage.postgres.command_wakeup import (
    _check_outbox_capacity,
    _envelope,
    command_scope_key,
    insert_command_outbox,
)
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_handoff import _terminal_session, _validate
from agent_storage.postgres.leases import (
    _active,
    _lock_epoch,
    _lock_lease_and_clock,
    lock_session_lease_boundary,
)

MAX_GENERATION = 5
MAX_TOTAL_AGE = timedelta(hours=24)
RETRY_DELAY = timedelta(seconds=60)


class RecoveryStatus(StrEnum):
    APPROVED = "approved"
    DEFERRED = "deferred"
    REQUIRES_RECONCILIATION = "requires_reconciliation"
    EXHAUSTED = "exhausted"
    IGNORED = "ignored"


@dataclass(frozen=True)
class CommandRecovery:
    accepted_event_id: UUID
    generation: int
    status: RecoveryStatus


def recover_command_batch(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    batch_size: int = 16,
) -> tuple[CommandRecovery, ...]:
    """Opt-in operator invocation; each candidate is one short, independently atomic TX.

    ponytail: every post-floor Event is quarantined, even harmless title changes.
    This trades availability for proof; later reconciliation can classify evidence.
    No background activation, model rerun, or business retry budget is introduced.
    """
    if (
        not isinstance(scope, PrincipalScope)
        or type(batch_size) is not int
        or not 1 <= batch_size <= 100
    ):
        raise ValueError("recovery requires trusted scope and an integer batch size from 1 to 100")
    database = _database(dsn, deployment_namespace)
    with database.connect() as connection:
        clock = connection.execute("SELECT clock_timestamp() AS now").fetchone()
        assert clock is not None
        now = clock["now"]
        rows = connection.execute(
            """SELECT accepted_event_id, session_id FROM session_command_pending
               WHERE deployment_namespace = %s AND scope_key = %s AND status = 'pending'
                 AND tenant_id = %s AND workspace_id = %s
                 AND origin = 'live' AND recovery_due_at <= %s
               ORDER BY recovery_due_at, accepted_event_id LIMIT %s""",
            (
                deployment_namespace,
                command_scope_key(scope),
                scope.tenant_id,
                scope.workspace_id,
                now,
                batch_size,
            ),
        ).fetchall()
    results = []
    for row in rows:
        with database.connect() as connection:
            connection.execute("SET LOCAL lock_timeout = '5s'")
            results.append(_recover(connection, deployment_namespace, scope, row))
    return tuple(results)


def _recover(
    connection: Any, namespace: str, scope: PrincipalScope, candidate: dict[str, Any]
) -> CommandRecovery:
    event_id = candidate["accepted_event_id"]
    session_id = SessionId(candidate["session_id"])
    lock_session_lease_boundary(connection, namespace, session_id)
    epoch = _lock_epoch(connection, namespace)
    lease, now = _lock_lease_and_clock(connection, namespace, session_id, update=True)
    # Match worker ordering; also stop an unfenced MESSAGE/command insert racing
    # the proof and approval. No stream/business lock is taken before the lease.
    stream = connection.execute(
        """SELECT current_version FROM session_streams
           WHERE deployment_namespace = %s AND session_id = %s FOR UPDATE""",
        (namespace, session_id),
    ).fetchone()
    pending = connection.execute(
        """SELECT * FROM session_command_pending WHERE deployment_namespace = %s
           AND accepted_event_id = %s FOR UPDATE""",
        (namespace, event_id),
    ).fetchone()
    assert pending is not None
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"].astimezone(UTC)
    generation = pending["current_generation"]

    def result(status: RecoveryStatus) -> CommandRecovery:
        return CommandRecovery(event_id, generation, status)

    if (
        pending["scope_key"] != command_scope_key(scope)
        or pending["tenant_id"] != scope.tenant_id
        or pending["workspace_id"] != scope.workspace_id
        or pending["session_id"] != session_id
    ):
        raise ValueError("command recovery scope mismatch")
    if (
        pending["status"] != "pending"
        or pending["origin"] != "live"
        or pending["recovery_due_at"] > now
    ):
        return result(RecoveryStatus.IGNORED)
    rollout = connection.execute(
        "SELECT admission_enabled FROM command_wakeup_rollouts "
        "WHERE deployment_namespace = %s FOR SHARE",
        (namespace,),
    ).fetchone()
    if rollout is None or not rollout["admission_enabled"]:
        return result(RecoveryStatus.IGNORED)
    if lease is not None and _active(lease, epoch, now):
        _defer(connection, namespace, event_id, now + RETRY_DELAY)
        return result(RecoveryStatus.DEFERRED)
    outbox = connection.execute(
        """SELECT * FROM broker_outbox WHERE deployment_namespace = %s AND scope_key = %s
           AND operation_id = %s AND wake_generation = %s
           AND message_type = 'zebra.session.command.ready'""",
        (namespace, pending["scope_key"], pending["command_id"], generation),
    ).fetchone()
    if outbox is not None and outbox["status"] == "dead":
        _stop(connection, namespace, event_id, "terminal_or_dead")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    try:
        if outbox is None:
            raise ValueError("missing command recovery outbox")
        _validate(connection, namespace, pending, outbox, scope, None)
    except (ValueError, TypeError, KeyError):
        # Only validated caller-scope derived pending is quarantined. Database
        # errors propagate and roll back; never store exception/input text.
        _stop(connection, namespace, event_id, "invalid_outbox")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    receipt = connection.execute(
        """SELECT * FROM command_handoff_receipts WHERE deployment_namespace = %s
           AND accepted_event_id = %s FOR UPDATE""",
        (namespace, event_id),
    ).fetchone()
    if _terminal_session(connection, namespace, session_id):
        _stop(connection, namespace, event_id, "terminal_or_dead")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    if receipt is not None:
        if receipt["handled_event_id"] is not None or receipt["status"] != "accepted":
            _stop(connection, namespace, event_id, "requires_reconciliation")
            return result(RecoveryStatus.REQUIRES_RECONCILIATION)
        # After a generation approval, the prior receipt remains until the next
        # actual handoff; it is not evidence that this newer generation ran.
        if receipt["wake_generation"] != generation:
            receipt = None
    floor = pending["accepted_sequence"] if receipt is None else receipt["execution_floor_sequence"]
    uncertain = floor is None or (receipt is not None and receipt["started_event_id"] is not None)
    if receipt is not None:
        uncertain = (
            uncertain
            or lease is None
            or any(
                lease[field] != receipt[field]
                for field in ("control_plane_epoch", "fencing_token", "owner_instance_id")
            )
        )
        if not uncertain and lease is not None and lease["expires_at"] > now:
            _defer(connection, namespace, event_id, now + RETRY_DELAY)
            return result(RecoveryStatus.DEFERRED)
    if not uncertain:
        uncertain = (
            connection.execute(
                """SELECT 1 FROM session_events WHERE deployment_namespace = %s
               AND session_id = %s AND sequence > %s LIMIT 1""",
                (namespace, session_id, floor),
            ).fetchone()
            is not None
        )
    if uncertain:
        _stop(connection, namespace, event_id, "requires_reconciliation")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    if generation >= MAX_GENERATION or now - pending["created_at"] >= MAX_TOTAL_AGE:
        _stop(connection, namespace, event_id, "recovery_exhausted")
        return result(RecoveryStatus.EXHAUSTED)
    if receipt is None and (
        outbox["status"] != "published"
        or outbox["published_at"] is None
        or outbox["published_at"] + RETRY_DELAY > now
    ):
        _defer(connection, namespace, event_id, now + RETRY_DELAY)
        return result(RecoveryStatus.DEFERRED)
    event_row = connection.execute(
        """SELECT event_id, session_id, sequence, event_type, payload, actor, created_at,
                  causation_id, correlation_id, idempotency_key, policy_version, model_profile
           FROM session_events WHERE deployment_namespace = %s AND event_id = %s""",
        (namespace, event_id),
    ).fetchone()
    assert event_row is not None and stream is not None
    envelope = _envelope(
        namespace, SessionEvent.model_validate(event_row), scope, generation=generation + 1
    )
    capacity = connection.execute(
        """SELECT max_unpublished_outbox, reserved_control_outbox
           FROM command_wakeup_rollouts WHERE deployment_namespace=%s""",
        (namespace,),
    ).fetchone()
    assert capacity is not None
    _check_outbox_capacity(
        connection,
        namespace,
        SessionCommandKind(pending["command_kind"]),
        max_unpublished_outbox=capacity["max_unpublished_outbox"],
        reserved_control_outbox=capacity["reserved_control_outbox"],
    )
    insert_command_outbox(connection, envelope)
    connection.execute(
        """INSERT INTO command_recovery_attempts (deployment_namespace, accepted_event_id,
           wake_generation, previous_message_id, message_id, approved_stream_sequence,
           reason, previous_receipt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            namespace,
            event_id,
            generation + 1,
            outbox["message_id"],
            envelope.message_id,
            stream["current_version"],
            "published_no_handoff" if receipt is None else "expired_unstarted",
            None if receipt is None else Jsonb(_receipt_snapshot(receipt)),
        ),
    )
    connection.execute(
        """UPDATE session_command_pending SET current_generation = %s, recovery_due_at = %s,
           recovery_code = NULL WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (generation + 1, now + RETRY_DELAY * min(2 ** (generation + 1), 15), namespace, event_id),
    )
    return CommandRecovery(event_id, generation + 1, RecoveryStatus.APPROVED)


def _receipt_snapshot(receipt: dict[str, Any]) -> dict[str, Any]:
    # Explicit allowlist: never let future receipt columns leak into audit JSON.
    fields = (
        "scope_key",
        "command_id",
        "accepted_event_id",
        "session_id",
        "status",
        "control_plane_epoch",
        "fencing_token",
        "owner_instance_id",
        "created_at",
        "execution_floor_sequence",
        "started_event_id",
        "handled_event_id",
        "turn_id",
        "wake_generation",
    )
    return {
        field: (value if value is None or isinstance(value, str | int) else str(value))
        for field in fields
        for value in (receipt[field],)
    }


def _defer(connection: Any, namespace: str, event_id: UUID, due: datetime) -> None:
    connection.execute(
        """UPDATE session_command_pending SET recovery_due_at = %s
           WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (due, namespace, event_id),
    )


def _stop(connection: Any, namespace: str, event_id: UUID, code: str) -> None:
    connection.execute(
        """UPDATE session_command_pending SET status = 'dead', recovery_code = %s
           WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (code, namespace, event_id),
    )
