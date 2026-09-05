"""Atomic command-to-Lease handoff shared by broker and fallback; no execution."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from agent_core.contracts.broker_envelope import (
    PrincipalScope,
    ZebraCommandEnvelope,
    parse_broker_envelope,
)
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.leases import DEFAULT_MAX_LEASE_TTL, LeaseConflictError, WorkerLease

from agent_storage.postgres.command_rollout import command_scope_mode
from agent_storage.postgres.command_wakeup import command_scope_key
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_message import (
    MessageInputRejected,
    append_command_message,
)
from agent_storage.postgres.command_wakeup_recovery_proof import recovery_approval
from agent_storage.postgres.command_wakeup_relay import _validated_body
from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.leases import acquire_lease_in_transaction, lock_session_lease_boundary


class HandoffStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    RETIRED_NOOP = "retired_noop"
    BUSY = "busy"
    PRIOR_COMMAND_UNRECONCILED = "prior_command_unreconciled"
    REQUIRES_RECONCILIATION = "requires_reconciliation"
    UNSUPPORTED_FOR_EXECUTION_HANDOFF = "unsupported_for_execution_handoff"
    SCOPE_DEFERRED = "scope_deferred"
    SCOPE_SETTLED = "scope_settled"


@dataclass(frozen=True)
class CommandHandoff:
    status: HandoffStatus
    command_id: UUID
    accepted_event_id: UUID
    lease: WorkerLease | None = None


class _TerminalAfterLease(Exception):
    """Roll back the tentative acquisition without discarding reconciliation."""


def handoff_command(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    accepted_event_id: UUID,
    owner_instance_id: str,
    ttl: timedelta,
    raw_body: bytes | None = None,
    maximum_ttl: timedelta = DEFAULT_MAX_LEASE_TTL,
    required_scope_mode: Literal["broker", "fallback"] | None = None,
) -> CommandHandoff:
    """Trusted scope is independent of the message; success is not scheduler ACK.

    Only a new ACCEPTED result carries execution authority. A duplicate never
    reacquires an expired lease. Historical ambiguity requires external accounting.
    MESSAGE input is atomic here; control commands use their dedicated path.
    """
    if not isinstance(scope, PrincipalScope) or not isinstance(accepted_event_id, UUID):
        raise ValueError("handoff requires trusted principal scope and canonical Event UUID")
    if required_scope_mode not in (None, "broker", "fallback"):
        raise ValueError("invalid required command scope mode")
    envelope = None
    if raw_body is not None:
        try:
            envelope = parse_broker_envelope(raw_body)
            if (
                not isinstance(envelope, ZebraCommandEnvelope)
                or envelope.scope != scope
                or envelope.deployment_namespace != deployment_namespace
                or envelope.accepted_event_id != str(accepted_event_id)
            ):
                raise ValueError("scope or identity mismatch")
        except ValueError:
            raise ValueError("invalid command handoff envelope or scope") from None
    with _database(dsn, deployment_namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout = '5s'")
        pending = connection.execute(
            """SELECT * FROM session_command_pending
               WHERE deployment_namespace = %s AND accepted_event_id = %s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        if (
            pending is None
            or pending["scope_key"] != command_scope_key(scope)
            or pending["tenant_id"] != scope.tenant_id
            or pending["workspace_id"] != scope.workspace_id
        ):
            raise ValueError("command handoff scope or canonical candidate mismatch")
        if required_scope_mode is not None:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,50))",
                (f"{deployment_namespace}:command-rollout:{pending['scope_key']}",),
            )
            mode = command_scope_mode(connection, deployment_namespace, pending["scope_key"])
            if required_scope_mode == "fallback" and mode == "broker":
                return CommandHandoff(
                    HandoffStatus.SCOPE_DEFERRED, pending["command_id"], accepted_event_id
                )
            if required_scope_mode == "broker" and mode != "broker":
                status = (
                    HandoffStatus.SCOPE_DEFERRED
                    if pending["status"] == "pending"
                    else HandoffStatus.SCOPE_SETTLED
                )
                return CommandHandoff(status, pending["command_id"], accepted_event_id)
        session_id = SessionId(pending["session_id"])
        lock_session_lease_boundary(connection, deployment_namespace, session_id)
        # No pending/Inbox lock before lease serialization: workers write those
        # after holding their existing lease SHARE and stream/projection locks.
        pending = connection.execute(
            """SELECT * FROM session_command_pending
               WHERE deployment_namespace = %s AND accepted_event_id = %s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        assert pending is not None
        outbox = connection.execute(
            """SELECT * FROM broker_outbox WHERE deployment_namespace = %s AND scope_key = %s
               AND message_type = 'zebra.session.command.ready' AND operation_id = %s
               AND wake_generation = %s""",
            (
                deployment_namespace,
                pending["scope_key"],
                pending["command_id"],
                pending["current_generation"] if envelope is None else envelope.wake_generation,
            ),
        ).fetchone()
        if outbox is None:
            raise ValueError("missing canonical command outbox")
        _validate(connection, deployment_namespace, pending, outbox, scope, raw_body)
        generation = outbox["wake_generation"]
        if generation < pending["current_generation"]:
            return CommandHandoff(HandoffStatus.DUPLICATE, pending["command_id"], accepted_event_id)
        if generation != pending["current_generation"]:
            raise ValueError("command generation has not been approved")
        retired = connection.execute(
            """SELECT 1 FROM command_retirements WHERE deployment_namespace=%s
               AND accepted_event_id=%s AND scope_key=%s AND session_id=%s AND command_id=%s""",
            (
                deployment_namespace,
                accepted_event_id,
                pending["scope_key"],
                session_id,
                pending["command_id"],
            ),
        ).fetchone()
        if retired is not None:
            return CommandHandoff(
                HandoffStatus.RETIRED_NOOP, pending["command_id"], accepted_event_id
            )
        approved = recovery_approval(
            connection, ZebraCommandEnvelope.model_validate(outbox["envelope_json"])
        )
        _check_inbox(connection, deployment_namespace, pending, outbox)
        receipt = connection.execute(
            """SELECT * FROM command_handoff_receipts WHERE deployment_namespace = %s
               AND scope_key = %s AND command_id = %s""",
            (deployment_namespace, pending["scope_key"], pending["command_id"]),
        ).fetchone()
        if receipt is not None:
            if (
                receipt["accepted_event_id"] != accepted_event_id
                or receipt["session_id"] != session_id
            ):
                raise ValueError("canonical command receipt identity conflict")
            if receipt["wake_generation"] == generation or receipt["handled_event_id"] is not None:
                _inbox(connection, deployment_namespace, pending, outbox, receipt["status"])
                status = (
                    HandoffStatus.DUPLICATE
                    if receipt["status"] == "accepted"
                    else HandoffStatus.REQUIRES_RECONCILIATION
                )
                return CommandHandoff(status, pending["command_id"], accepted_event_id)
            if (
                approved is None
                or receipt["wake_generation"] >= generation
                or receipt["started_event_id"] is not None
                or receipt["status"] != "accepted"
            ):
                raise ValueError("command receipt cannot be rebound without recovery proof")
        event = connection.execute(
            """SELECT payload FROM session_events
               WHERE deployment_namespace = %s AND event_id = %s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        assert event is not None
        lease = None
        execution_floor = None
        input_event_id = None if receipt is None else receipt["input_event_id"]
        if (
            pending["origin"] != "live"
            or pending["status"] != "pending"
            or _terminal_session(connection, deployment_namespace, session_id)
        ):
            status = HandoffStatus.REQUIRES_RECONCILIATION
        elif event["payload"]["kind"] not in ("run", "resume", "message"):
            return CommandHandoff(
                HandoffStatus.UNSUPPORTED_FOR_EXECUTION_HANDOFF,
                pending["command_id"],
                accepted_event_id,
            )
        else:
            # Only an exact handled Event receipt unblocks the next command.
            # Neither projection sequence nor a merely accepted handoff suffices.
            prior = connection.execute(
                """SELECT 1 FROM session_events AS event WHERE deployment_namespace = %s
                   AND session_id = %s AND event_type = 'session_command_accepted'
                   AND sequence < %s AND NOT EXISTS (
                       SELECT 1 FROM command_handoff_receipts AS receipt
                       WHERE receipt.deployment_namespace = event.deployment_namespace
                         AND receipt.accepted_event_id = event.event_id
                         AND receipt.session_id = event.session_id AND receipt.scope_key = %s
                         AND receipt.status = 'accepted' AND receipt.handled_event_id IS NOT NULL
                   ) AND NOT EXISTS (
                       SELECT 1 FROM command_control_receipts AS control
                       WHERE control.deployment_namespace = event.deployment_namespace
                         AND control.accepted_event_id = event.event_id
                         AND control.session_id = event.session_id AND control.scope_key = %s
                         AND control.kind = 'suspend' AND control.outcome = 'unsupported'
                   ) AND NOT EXISTS (
                       SELECT 1 FROM command_retirements AS retired
                       WHERE retired.deployment_namespace=event.deployment_namespace
                         AND retired.accepted_event_id=event.event_id
                         AND retired.session_id=event.session_id AND retired.scope_key=%s
                   ) LIMIT 1""",
                (
                    deployment_namespace,
                    session_id,
                    pending["accepted_sequence"],
                    pending["scope_key"],
                    pending["scope_key"],
                    pending["scope_key"],
                ),
            ).fetchone()
            if prior is not None:
                return CommandHandoff(
                    HandoffStatus.PRIOR_COMMAND_UNRECONCILED,
                    pending["command_id"],
                    accepted_event_id,
                )
            try:
                # Nested transaction is a savepoint. An old writer may have held
                # lease SHARE while terminalizing the projection during our wait.
                # Re-read AFTER lease serialization, never lock projection first.
                with connection.transaction():
                    lease = acquire_lease_in_transaction(
                        connection,
                        deployment_namespace,
                        session_id,
                        owner_instance_id=owner_instance_id,
                        ttl=ttl,
                        maximum_ttl=maximum_ttl,
                    )
                    if _terminal_session(connection, deployment_namespace, session_id):
                        raise _TerminalAfterLease
                    # Freshness floor only: old Events cannot be attributed to
                    # this new fence. This is NOT a handled-command watermark.
                    stream = connection.execute(
                        """SELECT current_version FROM session_streams
                           WHERE deployment_namespace = %s AND session_id = %s FOR UPDATE""",
                        (deployment_namespace, session_id),
                    ).fetchone()
                    assert stream is not None
                    if (
                        approved is not None
                        and stream["current_version"] != approved["approved_stream_sequence"]
                    ):
                        raise _TerminalAfterLease
                    execution_floor = stream["current_version"]
                    if event["payload"]["kind"] == "message":
                        accepted = read_event_in_transaction(
                            connection, deployment_namespace, EventId(accepted_event_id)
                        )
                        assert accepted is not None
                        message = append_command_message(
                            connection,
                            deployment_namespace,
                            accepted,
                            input_event_id=input_event_id,
                        )
                        input_event_id = message.event_id
                        execution_floor = max(execution_floor, message.sequence)
            except LeaseConflictError:
                return CommandHandoff(HandoffStatus.BUSY, pending["command_id"], accepted_event_id)
            except (_TerminalAfterLease, MessageInputRejected):
                lease = None
                execution_floor = None
                status = HandoffStatus.REQUIRES_RECONCILIATION
            else:
                status = HandoffStatus.ACCEPTED
        connection.execute(
            """INSERT INTO command_handoff_receipts (
                deployment_namespace, scope_key, command_id, accepted_event_id, session_id,
                status, control_plane_epoch, fencing_token, owner_instance_id,
                execution_floor_sequence, wake_generation, input_event_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (deployment_namespace, scope_key, command_id) DO UPDATE SET
                status = EXCLUDED.status, control_plane_epoch = EXCLUDED.control_plane_epoch,
                fencing_token = EXCLUDED.fencing_token,
                owner_instance_id = EXCLUDED.owner_instance_id,
                execution_floor_sequence = EXCLUDED.execution_floor_sequence,
                input_event_id = EXCLUDED.input_event_id,
                wake_generation = EXCLUDED.wake_generation, created_at = clock_timestamp(),
                started_event_id = NULL, handled_event_id = NULL, turn_id = NULL""",
            (
                deployment_namespace,
                pending["scope_key"],
                pending["command_id"],
                accepted_event_id,
                session_id,
                status.value,
                None if lease is None else lease.fence.control_plane_epoch,
                None if lease is None else lease.fence.fencing_token,
                None if lease is None else lease.fence.owner_instance_id,
                execution_floor,
                generation,
                input_event_id,
            ),
        )
        _inbox(connection, deployment_namespace, pending, outbox, status.value)
        return CommandHandoff(status, pending["command_id"], accepted_event_id, lease)


def _terminal_session(connection: Any, namespace: str, session_id: SessionId) -> bool:
    row = connection.execute(
        """SELECT status FROM session_projections
           WHERE deployment_namespace = %s AND session_id = %s""",
        (namespace, session_id),
    ).fetchone()
    return row is None or row["status"] in ("completed", "failed", "cancelled")


def _validate(
    connection: Any,
    namespace: str,
    pending: dict[str, Any],
    outbox: dict[str, Any],
    scope: PrincipalScope,
    raw: bytes | None,
) -> None:
    try:
        body = _validated_body(connection, namespace, outbox)
        envelope = parse_broker_envelope(body)
        if (
            not isinstance(envelope, ZebraCommandEnvelope)
            or envelope.scope != scope
            or envelope.accepted_event_id != str(pending["accepted_event_id"])
            or envelope.accepted_sequence != pending["accepted_sequence"]
            or envelope.aggregate_id != str(pending["session_id"])
            or envelope.operation_id != str(pending["command_id"])
            or command_scope_key(scope) != pending["scope_key"]
            or pending["tenant_id"] != scope.tenant_id
            or pending["workspace_id"] != scope.workspace_id
            or (raw is not None and raw != body)
        ):
            raise ValueError("invalid candidate")
    except (ValueError, TypeError, KeyError):
        raise ValueError("command handoff canonical identity or scope mismatch") from None


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
