"""Fallback-only poison isolation, revalidated against canonical state under locks."""

from hashlib import sha256
from uuid import UUID

from agent_core.contracts.broker_diagnostic import RejectionCode
from agent_core.domain.identifiers import EventId, SessionId

from agent_storage.postgres.command_wakeup import (
    _canonical_json,
    _scope_from_binding,
    command_scope_key,
)
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_handoff import _terminal_session, _validate
from agent_storage.postgres.command_wakeup_quarantine import (
    RejectionReceipt,
    record_rejection_in_transaction,
    validate_rejection_metadata,
)
from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.leases import (
    _lock_epoch,
    _lock_lease_and_clock,
    lock_session_lease_boundary,
)


def quarantine_candidate(
    dsn: str,
    *,
    deployment_namespace: str,
    consumer_role: str,
    accepted_event_id: UUID,
    code: RejectionCode,
) -> RejectionReceipt | None:
    """A stale/healthy hint is a no-op; uncertain identity can only record a diagnostic."""
    validate_rejection_metadata(consumer_role, code)
    if not isinstance(accepted_event_id, UUID) or code != "broker_hint_conflict":
        raise ValueError("invalid fallback quarantine hint")
    namespace = deployment_namespace
    with _database(dsn, namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        original = connection.execute(
            """SELECT * FROM session_command_pending WHERE deployment_namespace=%s
               AND accepted_event_id=%s""",
            (namespace, accepted_event_id),
        ).fetchone()
        if original is None:
            return None
        event = read_event_in_transaction(connection, namespace, EventId(accepted_event_id))
        if event is None:
            raise ValueError("fallback canonical Event unavailable")
        lock_session_lease_boundary(connection, namespace, event.session_id)
        _lock_epoch(connection, namespace)
        lease, _ = _lock_lease_and_clock(connection, namespace, event.session_id, update=True)
        connection.execute(
            """SELECT current_version FROM session_streams WHERE deployment_namespace=%s
               AND session_id=%s FOR UPDATE""",
            (namespace, event.session_id),
        ).fetchone()
        pending = connection.execute(
            """SELECT * FROM session_command_pending WHERE deployment_namespace=%s
               AND accepted_event_id=%s FOR UPDATE""",
            (namespace, accepted_event_id),
        ).fetchone()
        if pending is None or any(
            pending[key] != original[key]
            for key in ("session_id", "command_id", "scope_key", "current_generation")
        ):
            return None
        outbox = connection.execute(
            """SELECT * FROM broker_outbox WHERE deployment_namespace=%s AND operation_id=%s
               AND scope_key=%s AND wake_generation=%s
               AND message_type='zebra.session.command.ready'
               FOR SHARE""",
            (namespace, pending["command_id"], pending["scope_key"], pending["current_generation"]),
        ).fetchone()
        if outbox is None:
            raise ValueError("fallback diagnostic requires stored outbox evidence")
        body = _canonical_json(outbox["envelope_json"]).encode()
        identity = False
        try:
            scope = _scope_from_binding(connection, namespace, event)
            identity = (
                pending["scope_key"] == command_scope_key(scope)
                and pending["tenant_id"] == scope.tenant_id
                and pending["workspace_id"] == scope.workspace_id
                and pending["session_id"] == event.session_id
                and pending["accepted_sequence"] == event.sequence
                and str(pending["command_id"]) == event.payload["command_id"]
            )
            _validate(connection, namespace, pending, outbox, scope, None)
            if identity and pending["command_kind"] == event.payload["kind"]:
                return None
        except (ValueError, TypeError, KeyError):
            pass  # Validation only; DB errors propagate and roll back.
        receipt = record_rejection_in_transaction(
            connection, namespace, consumer_role, sha256(body).hexdigest(), len(body), code
        )
        protected = connection.execute(
            """SELECT 1 FROM command_handoff_receipts WHERE deployment_namespace=%s
               AND accepted_event_id=%s UNION ALL
               SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND sequence>%s AND event_type<>'session_title_updated' LIMIT 1""",
            (namespace, accepted_event_id, namespace, event.session_id, event.sequence),
        ).fetchone()
        if (
            identity
            and pending["status"] == "pending"
            and protected is None
            and (lease is None or lease["released_at"] is not None)
            and not _terminal_session(connection, namespace, SessionId(event.session_id))
        ):
            connection.execute(
                """UPDATE session_command_pending SET status='dead', recovery_code='invalid_outbox'
                   WHERE deployment_namespace=%s AND accepted_event_id=%s""",
                (namespace, accepted_event_id),
            )
        return receipt
