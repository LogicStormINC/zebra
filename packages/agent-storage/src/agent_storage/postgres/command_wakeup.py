"""Derived wakeup records in the canonical Event transaction, without broker IO."""

from __future__ import annotations

import json
from datetime import UTC
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.contracts.broker_envelope import (
    PrincipalScope,
    ZebraCommandEnvelope,
    ZebraCommandRef,
    parse_broker_envelope,
)
from agent_core.contracts.session_commands import SessionCommandAcceptedPayload, SessionCommandKind
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from psycopg import Error as PsycopgError
from psycopg.types.json import Jsonb
from pydantic import ValidationError


class CommandAdmissionCapacityError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def record_command_wakeup_in_transaction(
    connection: Any,
    deployment_namespace: str,
    event: SessionEvent,
    *,
    is_new_admission: bool = False,
) -> None:
    """Project one canonical accepted Event; no second execution lease or authority.

    Missing rollout rows are disabled. Rollout activation/backfill is an operator
    operation, not an environment flag or an HTTP-specific admission decision.
    """
    if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
        return
    rollout = connection.execute(
        """SELECT admission_enabled,
                  COALESCE((to_jsonb(rollout)->>'max_pending_per_scope')::int,32)
                      AS max_pending_per_scope,
                  COALESCE((to_jsonb(rollout)->>'max_pending_control_per_scope')::int,8)
                      AS max_pending_control_per_scope,
                  COALESCE((to_jsonb(rollout)->>'max_unpublished_outbox')::int,10000)
                      AS max_unpublished_outbox,
                  COALESCE((to_jsonb(rollout)->>'reserved_control_outbox')::int,64)
                      AS reserved_control_outbox
           FROM command_wakeup_rollouts rollout
           WHERE deployment_namespace = %s FOR SHARE""",
        (deployment_namespace,),
    ).fetchone()
    if rollout is None or not rollout["admission_enabled"]:
        return
    scope = _scope_from_binding(connection, deployment_namespace, event)
    envelope = _envelope(deployment_namespace, event, scope)
    scope_key = command_scope_key(scope)
    kind = SessionCommandKind(event.payload["kind"])
    # Stable per-scope sequence and capacity share one fixed global -> scope
    # transaction lock order. The sequence never changes when older rows finish.
    for identity in (
        f"{deployment_namespace}:command-global",
        f"{deployment_namespace}:command-scope:{scope_key}",
    ):
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 49))",
            (identity,),
        )
    existing = connection.execute(
        """SELECT accepted_event_id, session_id, accepted_sequence, tenant_id, workspace_id
           FROM session_command_pending
           WHERE deployment_namespace = %s AND scope_key = %s AND command_id = %s""",
        (deployment_namespace, scope_key, envelope.operation_id),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["accepted_event_id"]),
            str(existing["session_id"]),
            existing["accepted_sequence"],
            existing["tenant_id"],
            existing["workspace_id"],
        ) != (
            str(event.event_id),
            str(event.session_id),
            event.sequence,
            scope.tenant_id,
            scope.workspace_id,
        ):
            raise ValueError("command pending identity conflicts with canonical Event")
    else:
        _check_outbox_capacity(
            connection,
            deployment_namespace,
            kind,
            max_unpublished_outbox=rollout["max_unpublished_outbox"],
            reserved_control_outbox=rollout["reserved_control_outbox"],
        )
        next_scope_sequence = connection.execute(
            """SELECT COALESCE(MAX(scope_sequence), 0) + 1 AS value
               FROM session_command_pending
               WHERE deployment_namespace=%s AND scope_key=%s""",
            (deployment_namespace, scope_key),
        ).fetchone()["value"]
        connection.execute(
            """INSERT INTO session_command_pending (
               deployment_namespace, scope_key, scope_sequence, command_id, session_id,
               accepted_event_id, accepted_sequence, tenant_id, workspace_id, origin, command_kind
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                deployment_namespace,
                scope_key,
                next_scope_sequence,
                envelope.operation_id,
                event.session_id,
                event.event_id,
                event.sequence,
                scope.tenant_id,
                scope.workspace_id,
                "live" if is_new_admission else "historical",
                event.payload["kind"],
            ),
        )
        if is_new_admission:
            _check_scope_capacity(
                connection,
                deployment_namespace,
                scope_key,
                max_pending_per_scope=rollout["max_pending_per_scope"],
                max_pending_control_per_scope=rollout["max_pending_control_per_scope"],
                kind=kind,
            )
    outbox_exists = connection.execute(
        """SELECT 1 FROM broker_outbox WHERE deployment_namespace=%s AND scope_key=%s
           AND message_type=%s AND operation_id=%s AND wake_generation=%s""",
        (
            deployment_namespace,
            scope_key,
            envelope.message_type,
            envelope.operation_id,
            envelope.wake_generation,
        ),
    ).fetchone()
    if existing is not None and outbox_exists is None:
        _check_outbox_capacity(
            connection,
            deployment_namespace,
            kind,
            max_unpublished_outbox=rollout["max_unpublished_outbox"],
            reserved_control_outbox=rollout["reserved_control_outbox"],
        )
    insert_command_outbox(connection, envelope)


def _check_outbox_capacity(
    connection: Any,
    namespace: str,
    kind: SessionCommandKind,
    *,
    max_unpublished_outbox: int,
    reserved_control_outbox: int,
) -> None:
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 49))",
        (f"{namespace}:command-global",),
    )
    outbox_count = connection.execute(
        """SELECT count(*) AS total FROM broker_outbox
           WHERE deployment_namespace=%s AND status IN ('pending','publishing')""",
        (namespace,),
    ).fetchone()["total"]
    control = kind in {
        SessionCommandKind.CANCEL,
        SessionCommandKind.STOP,
        SessionCommandKind.SUSPEND,
    }
    execution_ceiling = max_unpublished_outbox - reserved_control_outbox
    if outbox_count >= (max_unpublished_outbox if control else execution_ceiling):
        raise CommandAdmissionCapacityError("command_outbox_capacity")


def _check_scope_capacity(
    connection: Any,
    namespace: str,
    scope_key: str,
    *,
    max_pending_per_scope: int,
    max_pending_control_per_scope: int,
    kind: SessionCommandKind,
) -> None:
    # Global Outbox capacity is locked first by the caller. A scope lock then
    # makes queued + handed-off-but-unfinished rows one durable admission budget.
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 49))",
        (f"{namespace}:command-scope:{scope_key}",),
    )
    control = kind in {
        SessionCommandKind.CANCEL,
        SessionCommandKind.STOP,
        SessionCommandKind.SUSPEND,
    }
    kinds = ("cancel", "stop", "suspend") if control else ("run", "resume", "message")
    scope_count = connection.execute(
        """SELECT count(*) AS total FROM session_command_pending
           WHERE deployment_namespace=%s AND scope_key=%s AND status='pending'
             AND command_kind = ANY(%s)""",
        (namespace, scope_key, list(kinds)),
    ).fetchone()["total"]
    ceiling = max_pending_control_per_scope if control else max_pending_per_scope
    if scope_count > ceiling:
        raise CommandAdmissionCapacityError("command_scope_capacity")


def insert_command_outbox(connection: Any, envelope: ZebraCommandEnvelope) -> None:
    """Insert the exact physical envelope, shared by admission and approved recovery."""
    body = _canonical_json(envelope.model_dump(mode="json"))
    parse_broker_envelope(body.encode("utf-8"))
    digest = sha256(body.encode("utf-8")).hexdigest()
    deployment_namespace = envelope.deployment_namespace
    scope_key = command_scope_key(envelope.scope)
    inserted = connection.execute(
        """
        INSERT INTO broker_outbox (
            deployment_namespace, message_id, scope_key, message_type, schema_version,
            aggregate_id, operation_id, wake_generation, envelope_json, envelope_digest
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING message_id
        """,
        (
            deployment_namespace,
            envelope.message_id,
            scope_key,
            envelope.message_type,
            1,
            envelope.aggregate_id,
            envelope.operation_id,
            envelope.wake_generation,
            Jsonb(envelope.model_dump(mode="json")),
            digest,
        ),
    ).fetchone()
    if inserted is None:
        existing = connection.execute(
            """SELECT message_id, envelope_digest FROM broker_outbox
               WHERE deployment_namespace = %s AND scope_key = %s AND message_type = %s
                 AND operation_id = %s AND wake_generation = %s""",
            (
                deployment_namespace,
                scope_key,
                envelope.message_type,
                envelope.operation_id,
                envelope.wake_generation,
            ),
        ).fetchone()
        if existing is None or (str(existing["message_id"]), existing["envelope_digest"]) != (
            envelope.message_id,
            digest,
        ):
            raise ValueError("Broker Outbox identity or digest conflicts with canonical Event")
    # Shadow evidence is deliberately best-effort and isolated by a savepoint;
    # it can never roll back canonical Event/Outbox admission.
    try:
        with connection.transaction():
            from agent_storage.postgres.command_rollout_shadow import record_command_shadow

            record_command_shadow(
                connection,
                deployment_namespace=deployment_namespace,
                source_message_id=UUID(envelope.message_id),
                scope_key=scope_key,
                envelope_digest=digest,
            )
    except (PsycopgError, ValueError):
        pass


def _scope_from_binding(connection: Any, namespace: str, event: SessionEvent) -> PrincipalScope:
    context = _validated_host_context(connection, namespace, event)
    assert context is not None
    try:
        return PrincipalScope(
            kind="principal", tenant_id=context.namespace_id, workspace_id=context.workspace_ref
        )
    except (ValidationError, ValueError):
        raise ValueError("command wakeup requires a valid, matching bounded Host scope") from None


def _validated_host_context(
    connection: Any, namespace: str, event: SessionEvent, *, allow_unbound: bool = False
) -> HostContextEnvelope | None:
    """Return the exact immutable context from the row whose identities we validate."""
    row = connection.execute(
        """
        SELECT session.namespace_id, segment.task_id, binding.snapshot_json, binding.binding_digest
        FROM session_projections AS session
        JOIN workspace_projections AS workspace
          ON workspace.deployment_namespace = session.deployment_namespace
         AND workspace.session_id = session.session_id
        JOIN execution_segments AS segment
          ON segment.deployment_namespace = session.deployment_namespace
         AND segment.session_id = session.session_id
        JOIN LATERAL (
            SELECT snapshot_json, binding_digest FROM task_binding_snapshots
            WHERE deployment_namespace = segment.deployment_namespace
              AND task_id = segment.task_id
            ORDER BY binding_revision DESC LIMIT 1
        ) AS binding ON TRUE
        WHERE session.deployment_namespace = %s AND session.session_id = %s
        """,
        (namespace, event.session_id),
    ).fetchone()
    if row is None:
        if allow_unbound:
            return None
        raise ValueError("command wakeup requires an authoritative Session and Task binding")
    try:
        binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
        host = binding.host_capability
        context = host.host_context
        if (
            binding.task_id != str(row["task_id"])
            or binding.binding_digest != row["binding_digest"]
        ):
            raise ValueError("inconsistent binding")
        if context is None and allow_unbound:
            return None
        session_namespace = row["namespace_id"]
        if session_namespace is None and context is not None:
            # Legacy handoffs omitted TASK_PREPARED.host_context. Recover identity
            # only from a same-Task parent with an already-bound namespace.
            parent = connection.execute(
                """SELECT parent.namespace_id FROM session_events received
                JOIN execution_segments child
                  ON child.deployment_namespace=received.deployment_namespace
                  AND child.session_id=received.session_id
                JOIN execution_segments source
                  ON source.deployment_namespace=child.deployment_namespace
                  AND source.task_id=child.task_id
                  AND source.session_id::text=received.payload->>'parent_session_id'
                JOIN session_projections parent
                  ON parent.deployment_namespace=source.deployment_namespace
                  AND parent.session_id=source.session_id
                WHERE received.deployment_namespace=%s AND received.session_id=%s
                  AND received.event_type='session_handoff_received'""",
                (namespace, event.session_id),
            ).fetchone()
            if parent is not None:
                session_namespace = parent["namespace_id"]
        if (
            context is None
            or host.grant_digest != host_context_digest(context)
                or host.namespace_id != context.namespace_id
                or session_namespace != context.namespace_id
                or host.host_app_id != context.host_app_id
            ):
            raise ValueError("inconsistent binding")
        # The frozen host workspace is the business scope, not a filesystem path.
        # Expiry is NOT re-admission: downstream execution still verifies authority.
        return context
    except (ValidationError, ValueError):
        raise ValueError("command wakeup requires a valid, matching bounded Host scope") from None


def _envelope(
    namespace: str, event: SessionEvent, scope: PrincipalScope, *, generation: int = 0
) -> ZebraCommandEnvelope:
    try:
        command = SessionCommandAcceptedPayload.model_validate(event.payload)
        if command.session_id != str(event.session_id):
            raise ValueError("command session mismatch")
        return ZebraCommandEnvelope(
            message_id=str(
                uuid5(NAMESPACE_URL, f"zebra-command:{namespace}:{event.event_id}:{generation}")
            ),
            message_type="zebra.session.command.ready",
            schema_version=1,
            deployment_namespace=namespace,
            scope=scope,
            aggregate_id=str(event.session_id),
            operation_id=str(UUID(command.command_id)),
            wake_generation=generation,
            # Child wakeups deliberately use an epoch-specific Event key, unlike payload.key.
            idempotency_key=event.idempotency_key or command.idempotency_key,
            correlation_id=str(event.correlation_id or event.event_id),
            causation_id=(
                str(
                    uuid5(
                        NAMESPACE_URL,
                        f"zebra-command:{namespace}:{event.event_id}:{generation - 1}",
                    )
                )
                if generation
                else str(event.causation_id)
                if event.causation_id
                else None
            ),
            occurred_at=event.created_at.astimezone(UTC).isoformat(),
            traceparent=None,
            payload_ref=ZebraCommandRef(kind="zebra_command", id=command.command_id),
            accepted_event_id=str(event.event_id),
            accepted_sequence=event.sequence,
        )
    except (ValidationError, ValueError):
        raise ValueError("invalid canonical command wakeup envelope") from None


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def command_scope_key(scope: PrincipalScope) -> str:
    return sha256(_canonical_json(scope.model_dump()).encode("utf-8")).hexdigest()
