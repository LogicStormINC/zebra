"""Read-only candidate proof before command snapshot preparation touches derived rows."""

from typing import Any
from uuid import UUID

from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

from agent_storage.postgres.command_read_state import command_event_at, finish_command_read_state
from agent_storage.postgres.command_rollout import command_scope_mode
from agent_storage.postgres.command_wakeup import command_scope_key
from agent_storage.postgres.command_wakeup_discovery import _database


def prepare_command_candidate(
    dsn: str,
    namespace: str,
    scope: PrincipalScope,
    accepted_id: UUID,
    raw: bytes | None,
    generation: int | None,
    scope_mode: str | None,
    *,
    message_only: bool = False,
) -> Any:
    # Import the existing proof at call time: handoff composes this preflight.
    from agent_storage.postgres.command_wakeup_handoff import _validate

    with _database(dsn, namespace).connect_task_io() as connection:
        pending = connection.execute(
            "SELECT * FROM session_command_pending WHERE deployment_namespace=%s "
            "AND accepted_event_id=%s",
            (namespace, accepted_id),
        ).fetchone()
        if pending is None or (
            pending["scope_key"],
            pending["tenant_id"],
            pending["workspace_id"],
        ) != (command_scope_key(scope), scope.tenant_id, scope.workspace_id):
            raise ValueError("command preparation scope or canonical candidate mismatch")
        outbox = connection.execute(
            "SELECT * FROM broker_outbox WHERE deployment_namespace=%s AND scope_key=%s "
            "AND operation_id=%s AND wake_generation=%s "
            "AND message_type='zebra.session.command.ready'",
            (
                namespace,
                pending["scope_key"],
                pending["command_id"],
                pending["current_generation"] if generation is None else generation,
            ),
        ).fetchone()
        if outbox is None:
            raise ValueError("missing canonical command outbox")
        _validate(connection, namespace, pending, outbox, scope, raw)
        if outbox["wake_generation"] != pending["current_generation"] or (
            pending["origin"] != "live" or pending["status"] != "pending"
        ):
            return None
        if scope_mode is not None and (
            (command_scope_mode(connection, namespace, pending["scope_key"]) == "broker")
            != (scope_mode == "broker")
        ):
            return None
        session_id = SessionId(pending["session_id"])
        event = command_event_at(connection, namespace, session_id, accepted_id)
        if event is None or event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
            raise ValueError("canonical command preparation Event is absent")
        if message_only and event.payload.get("kind") != "message":
            return None
    try:
        finish_command_read_state(dsn, deployment_namespace=namespace, session_id=session_id)
    except CheckpointNotReady:
        return pending
    return None
