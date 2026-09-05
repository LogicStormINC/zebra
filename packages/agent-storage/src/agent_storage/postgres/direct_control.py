"""Trusted direct cancellation, independent of stopped execution grant expiry."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthoritySnapshot
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.domain.workspaces import WorkspaceProjection

from agent_storage.postgres.command_wakeup import _scope_from_binding
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.session_cancellation import (
    cancel_in_transaction,
    lock_cancellation_context,
)
from agent_storage.postgres.task_admission import load_task_binding
from agent_storage.postgres.task_control_target import require_task_control_target


@dataclass(frozen=True)
class DirectCancellation:
    event: SessionEvent
    workspace: WorkspaceProjection


class PostgresDirectControl:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = _database(dsn, deployment_namespace)
        self.deployment_namespace = deployment_namespace
        self._binding_reader: Callable[[TaskId], TaskBindingSnapshot | None] = (
            lambda task_id: load_task_binding(
                dsn, deployment_namespace=deployment_namespace, task_id=task_id
            )
        )

    def load_task_binding(self, task_id: TaskId) -> TaskBindingSnapshot | None:
        return self._binding_reader(task_id)

    def host_scope(
        self, session_id: SessionId, context: HostContextEnvelope
    ) -> OpaqueAuthorityScope:
        with self._database.connect() as connection:
            return _host_scope(connection, self.deployment_namespace, session_id, context)

    def cancel(
        self,
        session_id: SessionId,
        *,
        scope: OpaqueAuthorityScope,
        workspace_ref: str | None = None,
        idempotency_key: str | None = None,
        operation_id: UUID | None = None,
        host_context: HostContextEnvelope | None = None,
        task_id: TaskId | None = None,
    ) -> DirectCancellation:
        if not isinstance(scope, OpaqueAuthorityScope) or (
            task_id is None and not scope.allows_session(session_id)
        ):
            raise ValueError("direct cancellation requires trusted caller scope")
        if task_id is not None and not isinstance(task_id, UUID):
            raise ValueError("invalid Task cancellation target")
        namespace = self.deployment_namespace
        if operation_id is not None and (
            not isinstance(operation_id, UUID) or idempotency_key is not None
        ):
            raise ValueError("invalid direct cancellation operation identity")
        normalized = (
            None if idempotency_key is None else (_request_key(session_id, idempotency_key))
        )
        key = (
            None
            if normalized is None
            else sha256(
                json.dumps(
                    [scope.authority_issuer, scope.namespace_id, workspace_ref, normalized],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        operation = operation_id or (
            uuid5(NAMESPACE_URL, f"direct-control:{namespace}:{key}") if key else uuid4()
        )
        scope_key = direct_scope_key(scope, workspace_ref)
        with self._database.connect() as connection:
            connection.execute("SET LOCAL lock_timeout='5s'")
            # Serialize explicit operation/key reuse across different Session targets.
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"direct-control:{namespace}:{operation}",),
            )
            previous = connection.execute(
                """SELECT * FROM direct_control_operations WHERE deployment_namespace=%s
                   AND (operation_id=%s OR (request_key=%s AND request_key IS NOT NULL))""",
                (namespace, operation, key),
            ).fetchone()
            if task_id is not None and previous is not None:
                if previous["scope_key"] != scope_key:
                    raise ValueError("direct cancellation idempotency conflict")
                session_id = SessionId(previous["session_id"])
            events, lease, now = lock_cancellation_context(connection, namespace, session_id)
            if host_context is not None:
                verified = _host_scope(connection, namespace, session_id, host_context)
                if (
                    verified.scope_key != scope.scope_key
                    or host_context.workspace_ref != workspace_ref
                ):
                    raise ValueError("direct cancellation Host identity conflicts")
                if task_id is not None:
                    scope = verified
            if not scope.allows_session(session_id):
                raise ValueError("direct cancellation requires trusted caller scope")
            validate_direct_scope(connection, namespace, session_id, scope, workspace_ref, events)
            if task_id is not None:
                require_task_control_target(
                    connection, namespace, task_id, session_id, replay=previous is not None
                )
            if previous is not None:
                if (
                    previous["operation_id"],
                    previous["session_id"],
                    previous["scope_key"],
                    previous["workspace_id"],
                ) != (operation, session_id, scope_key, workspace_ref):
                    raise ValueError("direct cancellation idempotency conflict")
                event = next(e for e in events if e.event_id == previous["terminal_event_id"])
                return DirectCancellation(
                    event,
                    rebuild_workspace([item for item in events if item.sequence <= event.sequence]),
                )
            if any(
                e.event_type
                in (
                    EventType.SESSION_CANCELLED,
                    EventType.SESSION_COMPLETED,
                    EventType.SESSION_FAILED,
                )
                for e in events
            ):
                raise ValueError("session cannot be cancelled from its current state")
            terminal, revoked = cancel_in_transaction(
                connection, namespace, events, lease, now, operation_id=operation, command=False
            )
            connection.execute(
                """INSERT INTO direct_control_operations
                   (deployment_namespace,operation_id,session_id,
                   authority_issuer,tenant_id,workspace_id,scope_key,request_key,terminal_event_id,
                   revoked_epoch,revoked_token,revoked_owner)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    namespace,
                    operation,
                    session_id,
                    scope.authority_issuer,
                    scope.namespace_id,
                    workspace_ref,
                    scope_key,
                    key,
                    terminal.event_id,
                    None if revoked is None else revoked["control_plane_epoch"],
                    None if revoked is None else revoked["fencing_token"],
                    None if revoked is None else revoked["owner_instance_id"],
                ),
            )
            connection.execute(
                """INSERT INTO command_runtime_cleanup (deployment_namespace,direct_operation_id,
                   session_id,scope_key,terminal_event_id) VALUES (%s,%s,%s,%s,%s)""",
                (namespace, operation, session_id, scope_key, terminal.event_id),
            )
            return DirectCancellation(terminal, rebuild_workspace(events))


def direct_scope_key(scope: OpaqueAuthorityScope, workspace_ref: str | None) -> str:
    return sha256(
        json.dumps([*scope.scope_key, workspace_ref], separators=(",", ":")).encode()
    ).hexdigest()


def _request_key(session_id: SessionId, key: str) -> str:
    try:
        return SessionCommand(
            session_id=session_id,
            kind=SessionCommandKind.CANCEL,
            expected_revision=0,
            idempotency_key=key,
        ).idempotency_key
    except ValueError:
        raise ValueError("invalid direct cancellation idempotency key") from None


def validate_direct_scope(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    scope: OpaqueAuthorityScope,
    workspace: str | None,
    events: list[SessionEvent],
) -> None:
    session = connection.execute(
        """SELECT namespace_id FROM session_projections
           WHERE deployment_namespace=%s AND session_id=%s""",
        (namespace, session_id),
    ).fetchone()
    if session is None or session["namespace_id"] not in (None, scope.namespace_id):
        raise ValueError("direct cancellation Session scope is unproven")
    row = connection.execute(
        """SELECT binding.snapshot_json,binding.binding_digest,segment.task_id
           FROM execution_segments segment JOIN task_binding_snapshots binding
             ON binding.deployment_namespace=segment.deployment_namespace
             AND binding.task_id=segment.task_id
           WHERE segment.deployment_namespace=%s AND segment.session_id=%s
           ORDER BY binding.binding_revision DESC LIMIT 1""",
        (namespace, session_id),
    ).fetchone()
    expected_workspace = None
    if row is not None:
        binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
        host = binding.host_capability
        if (
            binding.task_id != str(row["task_id"])
            or binding.binding_digest != row["binding_digest"]
            or (host.authority_issuer, host.namespace_id) != scope.scope_key
        ):
            raise ValueError("direct cancellation binding scope conflicts")
        if host.host_context is not None:
            expected_workspace = _scope_from_binding(connection, namespace, events[-1]).workspace_id
    else:
        # Cancellation uses identity evidence, not a now-expired execution permission.
        resolved = next(
            (
                event
                for event in reversed(events)
                if event.event_type is EventType.EXECUTION_AUTHORITY_RESOLVED
            ),
            None,
        )
        snapshot = (
            None
            if resolved is None
            else ExecutionAuthoritySnapshot.model_validate(resolved.payload)
        )
        if (
            snapshot is None
            or resolved is None
            or resolved.session_id != session_id
            or snapshot.scope.scope_key != scope.scope_key
        ):
            raise ValueError("direct cancellation authority identity is unproven")
    if expected_workspace != workspace:
        raise ValueError("direct cancellation workspace scope conflicts")


def _host_scope(
    connection: Any, namespace: str, session_id: SessionId, context: HostContextEnvelope
) -> OpaqueAuthorityScope:
    context.require_scope("agent.run")
    row = connection.execute(
        """SELECT binding.snapshot_json FROM execution_segments segment
        JOIN task_binding_snapshots binding
        ON binding.deployment_namespace=segment.deployment_namespace
        AND binding.task_id=segment.task_id WHERE segment.deployment_namespace=%s
        AND segment.session_id=%s ORDER BY binding.binding_revision DESC LIMIT 1""",
        (namespace, session_id),
    ).fetchone()
    binding = None if row is None else TaskBindingSnapshot.model_validate(row["snapshot_json"])
    bound = None if binding is None else binding.host_capability.host_context

    def principal(value: HostContextEnvelope) -> tuple[str, ...]:
        return tuple(
            ref.resource_id for ref in value.resource_refs if ref.resource_type == "principal"
        )

    if (
        binding is None
        or bound is None
        or (
            bound.host_app_id,
            bound.origin,
            bound.namespace_id,
            bound.workspace_ref,
            principal(bound),
        )
        != (
            context.host_app_id,
            context.origin,
            context.namespace_id,
            context.workspace_ref,
            principal(context),
        )
    ):
        raise ValueError("direct cancellation Host identity conflicts")
    return OpaqueAuthorityScope(
        authority_issuer=binding.host_capability.authority_issuer,
        namespace_id=context.namespace_id,
        allowed_session_ids=(str(session_id),),
    )
