"""Independent trusted control transaction; runtime destruction is never performed here."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from agent_core.contracts.broker_envelope import (
    PrincipalScope,
    ZebraCommandEnvelope,
    parse_broker_envelope,
)
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId

from agent_storage.postgres.command_rollout import command_scope_mode
from agent_storage.postgres.command_wakeup import command_scope_key
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_handoff import _validate
from agent_storage.postgres.leases import (
    lock_session_lease_boundary,
)
from agent_storage.postgres.session_cancellation import (
    cancel_in_transaction,
    lock_cancellation_context,
)


class ControlStatus(StrEnum):
    CANCELLED = "cancelled"
    TERMINAL_NOOP = "terminal_noop"
    UNSUPPORTED = "unsupported"
    REQUIRES_RECONCILIATION = "requires_reconciliation"
    DUPLICATE = "duplicate"
    SCOPE_DEFERRED = "scope_deferred"
    SCOPE_SETTLED = "scope_settled"


@dataclass(frozen=True)
class CommandControl:
    accepted_event_id: UUID
    status: ControlStatus
    terminal_event_id: UUID | None = None


def handle_control_command(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    accepted_event_id: UUID,
    raw_body: bytes | None = None,
    required_scope_mode: Literal["broker", "fallback"] | None = None,
) -> CommandControl:
    """CANCEL/STOP bypass execution capacity/prior commands. Cloud SUSPEND is rejected."""
    if not isinstance(scope, PrincipalScope) or not isinstance(accepted_event_id, UUID):
        raise ValueError("control requires trusted scope and canonical Event UUID")
    if required_scope_mode not in (None, "broker", "fallback"):
        raise ValueError("invalid required control scope mode")
    envelope = None if raw_body is None else parse_broker_envelope(raw_body)
    if envelope is not None and (
        not isinstance(envelope, ZebraCommandEnvelope)
        or envelope.scope != scope
        or envelope.deployment_namespace != deployment_namespace
        or envelope.accepted_event_id != str(accepted_event_id)
    ):
        raise ValueError("control envelope identity or scope mismatch")
    namespace = deployment_namespace
    with _database(dsn, namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout = '5s'")
        pending = connection.execute(
            """SELECT * FROM session_command_pending WHERE deployment_namespace=%s
               AND accepted_event_id=%s""",
            (namespace, accepted_event_id),
        ).fetchone()
        if (
            pending is None
            or pending["scope_key"] != command_scope_key(scope)
            or pending["tenant_id"] != scope.tenant_id
            or pending["workspace_id"] != scope.workspace_id
        ):
            raise ValueError("control scope or candidate mismatch")
        if required_scope_mode is not None:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,50))",
                (f"{namespace}:command-rollout:{pending['scope_key']}",),
            )
            mode = command_scope_mode(connection, namespace, pending["scope_key"])
            if required_scope_mode == "fallback" and mode == "broker":
                return CommandControl(accepted_event_id, ControlStatus.SCOPE_DEFERRED)
            if required_scope_mode == "broker" and mode != "broker":
                status = (
                    ControlStatus.SCOPE_DEFERRED
                    if pending["status"] == "pending"
                    else ControlStatus.SCOPE_SETTLED
                )
                return CommandControl(accepted_event_id, status)
        session_id = SessionId(pending["session_id"])
        lock_session_lease_boundary(connection, namespace, session_id)
        pending = connection.execute(
            """SELECT * FROM session_command_pending WHERE deployment_namespace=%s
               AND accepted_event_id=%s""",
            (namespace, accepted_event_id),
        ).fetchone()
        assert pending is not None
        generation = pending["current_generation"] if envelope is None else envelope.wake_generation
        outbox = connection.execute(
            """SELECT * FROM broker_outbox WHERE deployment_namespace=%s AND scope_key=%s
               AND operation_id=%s AND wake_generation=%s
               AND message_type='zebra.session.command.ready'""",
            (namespace, pending["scope_key"], pending["command_id"], generation),
        ).fetchone()
        if outbox is None:
            raise ValueError("missing canonical control outbox")
        _validate(connection, namespace, pending, outbox, scope, raw_body)
        if generation < pending["current_generation"]:
            return CommandControl(accepted_event_id, ControlStatus.DUPLICATE)
        if generation != pending["current_generation"]:
            raise ValueError("control generation is not approved")
        previous = connection.execute(
            """SELECT * FROM command_control_receipts WHERE deployment_namespace=%s
               AND accepted_event_id=%s""",
            (namespace, accepted_event_id),
        ).fetchone()
        if previous is not None:
            if (
                previous["scope_key"] != pending["scope_key"]
                or previous["command_id"] != pending["command_id"]
                or previous["session_id"] != session_id
            ):
                raise ValueError("control receipt identity conflict")
            _inbox(connection, namespace, pending, outbox)
            return CommandControl(
                accepted_event_id, ControlStatus.DUPLICATE, previous["terminal_event_id"]
            )
        events, lease, now = lock_cancellation_context(connection, namespace, session_id)
        accepted = next(event for event in events if event.event_id == accepted_event_id)
        kind = accepted.payload["kind"]
        if kind not in ("cancel", "stop", "suspend"):
            raise ValueError("command is not a control operation")
        terminal = None
        revoked = None
        if (
            pending["status"] != "pending"
            or pending["origin"] != "live"
            or outbox["status"] == "dead"
        ):
            outcome = ControlStatus.REQUIRES_RECONCILIATION
        elif kind == "suspend":
            outcome = ControlStatus.UNSUPPORTED
        else:
            terminal = next(
                (
                    event
                    for event in reversed(events)
                    if event.event_type
                    in {
                        EventType.SESSION_COMPLETED,
                        EventType.SESSION_FAILED,
                        EventType.SESSION_CANCELLED,
                    }
                ),
                None,
            )
            if terminal is not None:
                outcome = ControlStatus.TERMINAL_NOOP
            else:
                terminal, revoked = cancel_in_transaction(
                    connection,
                    namespace,
                    events,
                    lease,
                    now,
                    operation_id=accepted_event_id,
                    command=True,
                )
                outcome = ControlStatus.CANCELLED
        connection.execute(
            """INSERT INTO command_control_receipts (deployment_namespace, accepted_event_id,
               scope_key, command_id, session_id, kind, outcome, wake_generation,
               terminal_event_id, revoked_epoch, revoked_token, revoked_owner)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                namespace,
                accepted_event_id,
                pending["scope_key"],
                pending["command_id"],
                session_id,
                kind,
                outcome.value,
                generation,
                None if terminal is None else terminal.event_id,
                None if revoked is None else revoked["control_plane_epoch"],
                None if revoked is None else revoked["fencing_token"],
                None if revoked is None else revoked["owner_instance_id"],
            ),
        )
        if outcome is ControlStatus.CANCELLED:
            assert terminal is not None
            connection.execute(
                """INSERT INTO command_runtime_cleanup (deployment_namespace, accepted_event_id,
                   session_id, scope_key, terminal_event_id) VALUES (%s,%s,%s,%s,%s)""",
                (namespace, accepted_event_id, session_id, pending["scope_key"], terminal.event_id),
            )
        if outcome in (ControlStatus.CANCELLED, ControlStatus.TERMINAL_NOOP):
            connection.execute(
                """UPDATE session_command_pending SET status='cancelled', cancelled_by_control_id=%s
                   WHERE deployment_namespace=%s AND scope_key=%s AND session_id=%s
                     AND tenant_id=%s AND workspace_id=%s AND status='pending'
                     AND accepted_sequence<%s""",
                (
                    accepted_event_id,
                    namespace,
                    pending["scope_key"],
                    session_id,
                    scope.tenant_id,
                    scope.workspace_id,
                    pending["accepted_sequence"],
                ),
            )
        connection.execute(
            """UPDATE session_command_pending SET status=%s
               WHERE deployment_namespace=%s AND accepted_event_id=%s AND status='pending'""",
            (
                "dead" if outcome is ControlStatus.REQUIRES_RECONCILIATION else "done",
                namespace,
                accepted_event_id,
            ),
        )
        _inbox(connection, namespace, pending, outbox)
        return CommandControl(
            accepted_event_id, outcome, None if terminal is None else terminal.event_id
        )


def _inbox(
    connection: Any, namespace: str, pending: dict[str, Any], outbox: dict[str, Any]
) -> None:
    connection.execute(
        """INSERT INTO broker_control_inbox (deployment_namespace, message_id, accepted_event_id,
           envelope_digest, scope_key, command_id) VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT DO NOTHING""",
        (
            namespace,
            outbox["message_id"],
            pending["accepted_event_id"],
            outbox["envelope_digest"],
            pending["scope_key"],
            pending["command_id"],
        ),
    )
    row = connection.execute(
        "SELECT * FROM broker_control_inbox WHERE deployment_namespace=%s AND message_id=%s",
        (namespace, outbox["message_id"]),
    ).fetchone()
    if row is None or any(
        row[key] != value
        for key, value in {
            "accepted_event_id": pending["accepted_event_id"],
            "envelope_digest": outbox["envelope_digest"],
            "scope_key": pending["scope_key"],
            "command_id": pending["command_id"],
        }.items()
    ):
        raise ValueError("control Inbox identity conflict")
