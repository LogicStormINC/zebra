"""Validate control authority without inventing an executable lease or broker scope."""

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agent_core.contracts.session_commands import SessionCommandAcceptedPayload
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.task_bindings import TaskBindingSnapshot

from agent_storage.postgres.command_wakeup import _scope_from_binding, command_scope_key
from agent_storage.postgres.direct_control import direct_scope_key, validate_direct_scope


def cleanup_proof(connection: Any, namespace: str, obligation: dict[str, Any]) -> dict[str, Any]:
    if obligation["accepted_event_id"] is None:
        return _direct_proof(connection, namespace, obligation)
    receipt = connection.execute(
        """SELECT * FROM command_control_receipts WHERE deployment_namespace=%s
           AND accepted_event_id=%s""",
        (namespace, obligation["accepted_event_id"]),
    ).fetchone()
    accepted = _event(connection, namespace, obligation["accepted_event_id"])
    terminal = _event(connection, namespace, obligation["terminal_event_id"])
    if accepted.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
        raise ValueError("invalid_control_evidence")
    command = SessionCommandAcceptedPayload.model_validate(accepted.payload)
    scope = _scope_from_binding(connection, namespace, accepted)
    if (
        receipt is None
        or receipt["outcome"] != "cancelled"
        or receipt["kind"] not in ("cancel", "stop")
        or receipt["kind"] != command.kind.value
        or str(receipt["command_id"]) != command.command_id
        or str(accepted.session_id) != command.session_id
        or receipt["session_id"] != accepted.session_id
        or obligation["session_id"] != accepted.session_id
        or receipt["scope_key"] != command_scope_key(scope)
        or obligation["scope_key"] != receipt["scope_key"]
        or receipt["terminal_event_id"] != terminal.event_id
        or terminal.session_id != accepted.session_id
        or terminal.event_type is not EventType.SESSION_CANCELLED
        or terminal.actor is not EventActor.SYSTEM
        or terminal.causation_id != accepted.event_id
        or terminal.sequence <= accepted.sequence
    ):
        raise ValueError("invalid_control_evidence")
    if any(receipt[key] is None for key in ("revoked_epoch", "revoked_token", "revoked_owner")):
        raise ValueError("missing_revoked_fence")
    projection = connection.execute(
        """SELECT status FROM session_projections
           WHERE deployment_namespace=%s AND session_id=%s""",
        (namespace, accepted.session_id),
    ).fetchone()
    if projection is None or projection["status"] != "cancelled":
        raise ValueError("invalid_control_evidence")
    # _scope_from_binding already validates the frozen HostContext/issuer/digest.
    row = connection.execute(
        """SELECT binding.snapshot_json FROM execution_segments segment
           JOIN task_binding_snapshots binding
             ON binding.deployment_namespace=segment.deployment_namespace
             AND binding.task_id=segment.task_id
           WHERE segment.deployment_namespace=%s AND segment.session_id=%s
           ORDER BY binding.binding_revision DESC LIMIT 1""",
        (namespace, accepted.session_id),
    ).fetchone()
    binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
    return {
        **dict(receipt),
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "authority_issuer": binding.host_capability.authority_issuer,
    }


def _event(connection: Any, namespace: str, event_id: Any) -> SessionEvent:
    row = connection.execute(
        "SELECT * FROM session_events WHERE deployment_namespace=%s AND event_id=%s",
        (namespace, event_id),
    ).fetchone()
    if row is None:
        raise ValueError("invalid_control_evidence")
    return SessionEvent.model_validate(row)


def _direct_proof(connection: Any, namespace: str, obligation: dict[str, Any]) -> dict[str, Any]:
    operation = connection.execute(
        """SELECT * FROM direct_control_operations WHERE deployment_namespace=%s
           AND operation_id=%s""",
        (namespace, obligation["direct_operation_id"]),
    ).fetchone()
    terminal = _event(connection, namespace, obligation["terminal_event_id"])
    if operation is None or (
        operation["session_id"] != obligation["session_id"]
        or operation["scope_key"] != obligation["scope_key"]
        or operation["terminal_event_id"] != terminal.event_id
        or terminal.session_id != operation["session_id"]
        or terminal.event_type is not EventType.SESSION_CANCELLED
        or terminal.actor is not EventActor.SYSTEM
        or terminal.causation_id is not None
        or terminal.event_id
        != uuid5(
            NAMESPACE_URL,
            f"zebra-direct-control:{namespace}:{operation['operation_id']}:{EventType.SESSION_CANCELLED.value}",
        )
        or terminal.idempotency_key
        != f"direct-control:{operation['operation_id']}:{EventType.SESSION_CANCELLED.value}"
    ):
        raise ValueError("invalid_control_evidence")
    rows = connection.execute(
        """SELECT * FROM session_events WHERE deployment_namespace=%s
        AND session_id=%s ORDER BY sequence""",
        (namespace, terminal.session_id),
    ).fetchall()
    scope = OpaqueAuthorityScope(
        authority_issuer=operation["authority_issuer"], namespace_id=operation["tenant_id"]
    )
    if operation["scope_key"] != direct_scope_key(scope, operation["workspace_id"]):
        raise ValueError("invalid_control_evidence")
    validate_direct_scope(
        connection,
        namespace,
        terminal.session_id,
        scope,
        operation["workspace_id"],
        [SessionEvent.model_validate(row) for row in rows],
    )
    projection = connection.execute(
        """SELECT status FROM session_projections
        WHERE deployment_namespace=%s AND session_id=%s""",
        (namespace, terminal.session_id),
    ).fetchone()
    if projection is None or projection["status"] != "cancelled":
        raise ValueError("invalid_control_evidence")
    if any(operation[key] is None for key in ("revoked_epoch", "revoked_token", "revoked_owner")):
        raise ValueError("missing_revoked_fence")
    return dict(operation)
