"""Trusted direct cancellation, independent of stopped execution grant expiry."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from agent_core.application.session_command_read_state import SessionCommandReadState
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthoritySnapshot
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot, require_task_host_context
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

from agent_storage.postgres.command_read_budget import command_read_budget
from agent_storage.postgres.command_read_state import (
    CommandReadPreparing,
    command_event_at,
    finish_command_read_state,
)
from agent_storage.postgres.command_wakeup import _scope_from_binding
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.session_cancellation import (
    cancel_in_transaction,
    lock_cancellation_context,
)
from agent_storage.postgres.task_admission import load_task_binding
from agent_storage.postgres.task_control_target import require_task_control_target
from agent_storage.postgres.task_io import TaskIoConnections
from agent_storage.postgres.work_unit import postgres_transaction_work_unit
from agent_storage.postgres.workspaces import get_workspace_in_transaction
from agent_storage.task_read_summary_rows import encoded

if TYPE_CHECKING:
    from agent_storage.postgres.stream_proof_batch import StreamProofSnapshot


@dataclass(frozen=True)
class DirectCancellation:
    event: SessionEvent
    workspace: WorkspaceProjection


class PostgresDirectControl:
    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        task_io_connections: TaskIoConnections | None = None,
    ) -> None:
        validated = _database(dsn, deployment_namespace)
        shared = task_io_connections if task_io_connections is not None else TaskIoConnections(dsn)
        # Retain the command namespace validation above; inject addresses only.
        self._database = PostgresDatabase(
            dsn, deployment_namespace=validated.deployment_namespace, task_io_connections=shared
        )
        self.deployment_namespace = deployment_namespace
        self._binding_reader: Callable[[TaskId], TaskBindingSnapshot | None] = (
            lambda task_id: load_task_binding(
                dsn,
                deployment_namespace=deployment_namespace,
                task_id=task_id,
                task_io_connections=shared,
            )
        )

        self._native_binding_reader = self._binding_reader

    def load_task_binding(self, task_id: TaskId) -> TaskBindingSnapshot | None:
        return self._binding_reader(task_id)

    _snapshot_native_load = load_task_binding

    def supports_binding_snapshot(self, database: PostgresDatabase) -> bool:
        method = self.load_task_binding
        return (
            type(self) is PostgresDirectControl
            and self._binding_reader is self._native_binding_reader
            and getattr(method, "__func__", method) is PostgresDirectControl._snapshot_native_load
            and self._database._dsn == database._dsn
            and self._database.deployment_namespace == database.deployment_namespace
        )

    def read_task_binding_snapshot(
        self, proof: "StreamProofSnapshot", task_id: TaskId
    ) -> TaskBindingSnapshot | None:
        if not self.supports_binding_snapshot(proof._database):
            return self.load_task_binding(task_id)
        return proof.read_task_binding(task_id)

    def host_scope(
        self, session_id: SessionId, context: HostContextEnvelope
    ) -> OpaqueAuthorityScope:
        with self._database.connect_task_io() as connection:
            return _host_scope(connection, self.deployment_namespace, session_id, context)

    @command_read_budget
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
        preparation: ClientPreparationContext | None = None,
        authorize_preparation: Callable[[], None] | None = None,
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
        if (preparation is None) != (authorize_preparation is None):
            raise ValueError("native preparation requires its current authorization")
        if preparation is not None:
            if preparation.operation_id != operation or (
                task_id is not None and preparation.task_id != task_id
            ):
                raise ValueError("native cancellation preparation scope conflicts")
            SessionCommand(
                session_id=session_id,
                kind=SessionCommandKind.CANCEL,
                expected_revision=0,
                idempotency_key=str(operation),
                payload={
                    "input": preparation.input,
                    "client_preparation": preparation.model_dump(mode="json", exclude={"input"}),
                },
            )
        scope_key = direct_scope_key(scope, workspace_ref)
        with self._database.connect_task_io() as connection:
            validate_direct_scope(connection, namespace, session_id, scope, workspace_ref)
        try:
            finish_command_read_state(
                self._database._dsn, deployment_namespace=namespace, session_id=session_id
            )
        except CheckpointNotReady as progress:
            raise CommandReadPreparing("direct cancellation read state is preparing") from progress
        with self._database.connect_task_io() as connection:
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
            try:
                state, lease, now = lock_cancellation_context(connection, namespace, session_id)
            except CheckpointNotReady as progress:
                raise CommandReadPreparing("direct cancellation source advanced") from progress
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
            validate_direct_scope(connection, namespace, session_id, scope, workspace_ref, state)
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
                event = command_event_at(
                    connection, namespace, session_id, previous["terminal_event_id"]
                )
                if event is None or previous["workspace_snapshot_json"] is None:
                    raise ValueError("direct cancellation receipt lacks exact canonical snapshot")
                return DirectCancellation(
                    event,
                    WorkspaceProjection.model_validate_json(previous["workspace_snapshot_json"]),
                )
            if state.terminal_event_id is not None:
                raise ValueError("session cannot be cancelled from its current state")
            if preparation is None:
                terminal, revoked = cancel_in_transaction(
                    connection, namespace, state, lease, now, operation_id=operation, command=False
                )
            else:
                # The native cancellation lock order stays authoritative. All
                # transport-specific current checks borrow this exact transaction.
                with postgres_transaction_work_unit(self._database, connection):
                    assert authorize_preparation is not None
                    authorize_preparation()
                    terminal, revoked = cancel_in_transaction(
                        connection,
                        namespace,
                        state,
                        lease,
                        now,
                        operation_id=operation,
                        command=False,
                        preparation=preparation,
                    )
            workspace = get_workspace_in_transaction(connection, namespace, session_id)
            assert workspace is not None
            connection.execute(
                """INSERT INTO direct_control_operations
                   (deployment_namespace,operation_id,session_id,
                   authority_issuer,tenant_id,workspace_id,scope_key,request_key,terminal_event_id,
                   revoked_epoch,revoked_token,revoked_owner,workspace_snapshot_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
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
                    encoded(workspace.model_dump(mode="json"), 1_048_576),
                ),
            )
            connection.execute(
                """INSERT INTO command_runtime_cleanup (deployment_namespace,direct_operation_id,
                   session_id,scope_key,terminal_event_id) VALUES (%s,%s,%s,%s,%s)""",
                (namespace, operation, session_id, scope_key, terminal.event_id),
            )
            return DirectCancellation(terminal, workspace)


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
    events: SessionCommandReadState | list[SessionEvent] | None = None,
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
            last = (
                command_event_at(connection, namespace, session_id, events.last_event_id)
                if isinstance(events, SessionCommandReadState) and events.last_event_id is not None
                else events[-1]
                if isinstance(events, list) and events
                else _identity_event(connection, namespace, session_id)
            )
            if last is None:
                raise ValueError("direct cancellation canonical frontier is unproven")
            expected_workspace = _scope_from_binding(connection, namespace, last).workspace_id
    else:
        # Cancellation uses identity evidence, not a now-expired execution permission.
        resolved = (
            command_event_at(connection, namespace, session_id, events.resolved_event_id)
            if isinstance(events, SessionCommandReadState) and events.resolved_event_id is not None
            else _identity_event(connection, namespace, session_id, resolved=True)
            if events is None
            else next(
                (
                    event
                    for event in reversed(events if isinstance(events, list) else [])
                    if event.event_type is EventType.EXECUTION_AUTHORITY_RESOLVED
                ),
                None,
            )
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


def _identity_event(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    *,
    resolved: bool = False,
) -> SessionEvent | None:
    row = connection.execute(
        "SELECT event_id FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
        + ("AND event_type='execution_authority_resolved' " if resolved else "")
        + "ORDER BY sequence DESC LIMIT 1",
        (namespace, session_id),
    ).fetchone()
    return (
        None
        if row is None
        else command_event_at(connection, namespace, session_id, row["event_id"])
    )


def _host_scope(
    connection: Any, namespace: str, session_id: SessionId, context: HostContextEnvelope
) -> OpaqueAuthorityScope:
    context.require_scope("agent.run")
    row = connection.execute(
        """SELECT segment.task_id, binding.snapshot_json FROM execution_segments segment
        JOIN task_binding_snapshots binding
        ON binding.deployment_namespace=segment.deployment_namespace
        AND binding.task_id=segment.task_id WHERE segment.deployment_namespace=%s
        AND segment.session_id=%s ORDER BY binding.binding_revision DESC LIMIT 1""",
        (namespace, session_id),
    ).fetchone()
    binding = None if row is None else TaskBindingSnapshot.model_validate(row["snapshot_json"])
    if binding is None:
        raise ValueError("direct cancellation Host identity conflicts")
    require_task_host_context(binding, context, task_id=str(row["task_id"]), now=datetime.now(UTC))
    return OpaqueAuthorityScope(
        authority_issuer=binding.host_capability.authority_issuer,
        namespace_id=context.namespace_id,
        allowed_session_ids=(str(session_id),),
    )
