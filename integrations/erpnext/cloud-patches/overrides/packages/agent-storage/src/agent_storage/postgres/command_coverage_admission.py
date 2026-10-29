"""Canonical strict command admission and process routing in the caller transaction."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.contracts.session_commands import SessionCommandKind
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.task_admission_transaction import TaskAdmissionReceipt, TaskAdmissionRequest

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_event_positions import _lock_task
from agent_storage.postgres.worker_capability import (
    STRICT_WORKER_CONTRACT,
    WorkerCapabilityLease,
    WorkerCapabilityLostError,
    check_worker_capability_clock,
    pin_worker_capability,
)
from agent_storage.worker_capability_configuration import (
    CONTINUATION_PROTOCOL,
    continuation_configuration_digest,
)

CONTROL_KINDS = {SessionCommandKind.STOP, SessionCommandKind.CANCEL, SessionCommandKind.SUSPEND}


def reject_missing_command_consumer(
    connection: Any, namespace: str, accepted_event_id: UUID,
    consumer_capability: WorkerCapabilityLease | None,
) -> None:
    """Negative-only preflight; never substitutes for final locked admission.

    An unregistered consumer cannot run expensive strict recovery first. Non-
    strict commands still use the ordinary path without a process capability.
    """
    if consumer_capability is None and connection.execute(
        "SELECT 1 FROM command_coverage_requirements "
        "WHERE deployment_namespace=%s AND accepted_event_id=%s",
        (namespace, accepted_event_id),
    ).fetchone() is not None:
        raise WorkerCapabilityLostError("strict command requires a qualified consumer")


def admit_coverage_task(
    dsn: str,
    namespace: str,
    request: TaskAdmissionRequest,
    configuration_digest: str,
) -> TaskAdmissionReceipt:
    """Reuse Task admission on ONE connection; trailing command gates native wake."""
    from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction

    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        lease = pin_worker_capability(
            connection,
            namespace,
            contract=STRICT_WORKER_CONTRACT,
            configuration_digest=configuration_digest,
        )
        connection.execute(
            "SELECT set_config('zebra.coverage_configuration',%s,true)",
            (configuration_digest,),
        )
        receipt = PostgresTaskAdmissionTransaction(
            dsn,
            deployment_namespace=namespace,
        ).admit_in_transaction(connection, namespace, request)
        check_worker_capability_clock(connection, lease)
        return receipt


def strict_command_source(connection: Any, namespace: str, session_id: UUID) -> Any:
    """Any raw Task-prepared marker is strict, including later Segment markers."""
    rows = connection.execute(
        """SELECT t.task_id,t.root_session_id,e.event_id AS bootstrap_event_id,e.payload,
                  e.session_id AS prepared_session_id,e.sequence AS prepared_sequence,
                  e.created_at AS prepared_created_at,
                  b.snapshot_json,b.binding_digest,b.binding_revision
        FROM execution_segments s JOIN agent_tasks t
          ON t.deployment_namespace=s.deployment_namespace AND t.task_id=s.task_id
        JOIN execution_segments source ON source.deployment_namespace=t.deployment_namespace
          AND source.task_id=t.task_id
        LEFT JOIN session_events e ON e.deployment_namespace=t.deployment_namespace
          AND e.session_id=source.session_id AND e.event_type='task_prepared'
        LEFT JOIN LATERAL (SELECT snapshot_json,binding_digest,binding_revision
          FROM task_binding_snapshots WHERE deployment_namespace=t.deployment_namespace
            AND task_id=t.task_id ORDER BY binding_revision DESC LIMIT 1) b ON TRUE
        WHERE s.deployment_namespace=%s AND s.session_id=%s
          AND (EXISTS (
            SELECT 1 FROM execution_segments marker_segment JOIN session_events marker
              ON marker.deployment_namespace=marker_segment.deployment_namespace
              AND marker.session_id=marker_segment.session_id AND marker.event_type='task_prepared'
            WHERE marker_segment.deployment_namespace=t.deployment_namespace
              AND marker_segment.task_id=t.task_id AND marker.payload ? 'coverage_admission'
          ) OR EXISTS (
            SELECT 1 FROM command_coverage_requirements requirement
            WHERE requirement.deployment_namespace=t.deployment_namespace
              AND requirement.task_id=t.task_id
          ))
        ORDER BY source.segment_index,e.sequence LIMIT 65""",
        (namespace, session_id),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise WorkerCapabilityLostError("mixed or repeated strict Task bootstrap markers")
    row = rows[0]
    if (
        row["prepared_session_id"] != row["root_session_id"]
        or row["prepared_sequence"] != 2
        or not isinstance(row["payload"], dict)
        or "coverage_admission" not in row["payload"]
    ):
        raise WorkerCapabilityLostError("strict marker is not the canonical root bootstrap")
    return row


def _identity(
    connection: Any,
    namespace: str,
    session_id: UUID,
    *,
    lock_task_authority: bool = False,
    authority_deadlines: list[datetime] | None = None,
    lock_registry: bool = True,
) -> dict[str, Any] | None:
    row = strict_command_source(connection, namespace, session_id)
    if row is None:
        return None
    if lock_task_authority:
        _lock_task(connection, namespace, TaskId(row["task_id"]), shared=True)
        row = strict_command_source(connection, namespace, session_id)
        if row is None:
            raise WorkerCapabilityLostError(
                "strict Task identity changed while acquiring renewal lock"
            )
    if row["root_session_id"] != session_id:
        raise WorkerCapabilityLostError("strict contract does not support new Session handoff")
    try:
        binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
    except ValueError:
        raise WorkerCapabilityLostError("strict command binding is malformed") from None
    host = binding.host_capability
    context = host.host_context
    if (
        binding.task_id != str(row["task_id"])
        or binding.binding_digest != row["binding_digest"]
        or binding.binding_revision != row["binding_revision"]
        or context is None
        or context.expires_at is None
        or host.grant_digest != host_context_digest(context)
        or context.namespace_id != host.namespace_id
        or context.host_app_id != host.host_app_id
        or row["payload"].get("host_context") is None
    ):
        raise WorkerCapabilityLostError("strict command frozen binding is invalid")
    registry = connection.execute(
        """SELECT issuer FROM host_authority_registries WHERE deployment_namespace=%s
        AND host_app_id=%s AND namespace_id=%s AND issuer=%s AND active"""
        + (" FOR SHARE" if lock_registry else ""),
        (namespace, host.host_app_id, host.namespace_id, host.authority_issuer),
    ).fetchone()
    stamp = connection.execute("SELECT clock_timestamp() AS now").fetchone()
    if registry is None or stamp is None or host.grant_expires_at is None:
        raise WorkerCapabilityLostError("strict command current Host authority is unavailable")
    try:
        admission = validate_coverage_admission(
            row["payload"]["coverage_admission"],
            host_context=context,
            now=stamp["now"],
        )
    except ValueError:
        raise WorkerCapabilityLostError("strict command admission authority is invalid") from None
    if host.grant_expires_at <= stamp["now"]:
        raise WorkerCapabilityLostError("strict command Host binding expired")
    runtime_deadline = row["prepared_created_at"] + timedelta(seconds=admission.max_runtime_seconds)
    if runtime_deadline <= stamp["now"]:
        raise WorkerCapabilityLostError("strict Task runtime deadline expired")
    if authority_deadlines is not None:
        authority_deadlines.extend((host.grant_expires_at, context.expires_at, runtime_deadline))
    return {
        "task_id": row["task_id"],
        "session_id": session_id,
        "bootstrap_event_id": row["bootstrap_event_id"],
        "binding_revision": row["binding_revision"],
        "binding_digest": row["binding_digest"],
        "admission_digest": sha256(
            json.dumps(
                admission.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "contract": STRICT_WORKER_CONTRACT,
    }


def admit_strict_command(
    connection: Any,
    namespace: str,
    event: SessionEvent,
    *,
    native_enabled: bool,
) -> WorkerCapabilityLease | None:
    if event.payload.get("kind") in CONTROL_KINDS:
        return None
    identity = _identity(connection, namespace, event.session_id)
    if identity is None:
        return None
    if not native_enabled:
        raise WorkerCapabilityLostError("strict command requires native admission rollout")
    existing = connection.execute(
        """SELECT configuration_digest,contract FROM command_coverage_requirements
        WHERE deployment_namespace=%s AND task_id=%s ORDER BY accepted_event_id LIMIT 1""",
        (namespace, identity["task_id"]),
    ).fetchone()
    configured = connection.execute(
        "SELECT current_setting('zebra.coverage_configuration',true) AS digest"
    ).fetchone()
    supplied = None if configured is None else configured["digest"] or None
    if existing is None:
        digest = supplied
    else:
        digest = existing["configuration_digest"]
        if existing["contract"] != identity["contract"] or supplied not in (None, digest):
            raise WorkerCapabilityLostError("strict command deployment requirement changed")
    if digest is None:
        raise WorkerCapabilityLostError("trusted strict deployment configuration is unavailable")
    lease = pin_worker_capability(
        connection,
        namespace,
        contract=identity["contract"],
        configuration_digest=digest,
    )
    identity["configuration_digest"] = digest
    columns = tuple(identity)
    inserted = connection.execute(
        "INSERT INTO command_coverage_requirements (deployment_namespace,accepted_event_id,"
        + ",".join(columns)
        + ") VALUES ("
        + ",".join(["%s"] * (len(columns) + 2))
        + ") ON CONFLICT (deployment_namespace,accepted_event_id) DO UPDATE SET "
        "configuration_digest=command_coverage_requirements.configuration_digest RETURNING *",
        (namespace, event.event_id, *identity.values()),
    ).fetchone()
    if inserted is None or any(inserted[key] != value for key, value in identity.items()):
        raise WorkerCapabilityLostError("strict accepted Event requirement is immutable")
    return lease


def pin_command_consumer(
    connection: Any,
    namespace: str,
    accepted_event_id: UUID,
    consumer_capability: WorkerCapabilityLease | None,
    *,
    lock_task_authority: bool = False,
) -> WorkerCapabilityLease | None:
    """Main handoff seam: invoke BEFORE lease boundary/pending/Inbox mutations.

    WorkerCapabilityLostError means defer, never ACK or quarantine. A final clock
    check after ALL writes must raise to roll back tentative ownership on expiry.
    """
    event = connection.execute(
        "SELECT session_id,payload FROM session_events "
        "WHERE deployment_namespace=%s AND event_id=%s",
        (namespace, accepted_event_id),
    ).fetchone()
    if event is None or SessionCommandKind(event["payload"]["kind"]) in CONTROL_KINDS:
        return None
    identity = _identity(
        connection, namespace, event["session_id"], lock_task_authority=lock_task_authority
    )
    if identity is None:
        return None
    row = connection.execute(
        """SELECT q.*,a.reason AS recovery_reason,
           a.coverage_proof->>'continuation_protocol' AS continuation_protocol
           FROM command_coverage_requirements q
           LEFT JOIN session_command_pending p ON p.deployment_namespace=q.deployment_namespace
             AND p.accepted_event_id=q.accepted_event_id
           LEFT JOIN command_recovery_attempts a ON a.deployment_namespace=p.deployment_namespace
             AND a.accepted_event_id=p.accepted_event_id AND a.wake_generation=p.current_generation
           WHERE q.deployment_namespace=%s AND q.accepted_event_id=%s""",
        (namespace, accepted_event_id),
    ).fetchone()
    if row is None or any(row[key] != value for key, value in identity.items()):
        raise WorkerCapabilityLostError(
            "strict command canonical requirement is missing or changed"
        )
    protocol = row["continuation_protocol"]
    if protocol is not None and (
        protocol != CONTINUATION_PROTOCOL or row["recovery_reason"] != "coverage_continuation"
    ):
        raise WorkerCapabilityLostError("unsupported native continuation approval")
    lease = pin_worker_capability(
        connection,
        namespace,
        contract=row["contract"],
        configuration_digest=row["configuration_digest"],
        consumer_capability=consumer_capability,
        require_process=True,
        continuation_digest=(
            continuation_configuration_digest(row["configuration_digest"])
            if protocol is not None else None
        ),
    )
    deadlines: list[datetime] = []
    if (
        _identity(
            connection,
            namespace,
            event["session_id"],
            lock_task_authority=lock_task_authority,
            authority_deadlines=deadlines,
        )
        != identity
    ):
        raise WorkerCapabilityLostError("strict Task authority changed while pinning capability")
    pinned = replace(lease, expires_at=min([lease.expires_at, *deadlines]))
    check_worker_capability_clock(connection, pinned)
    return pinned


__all__ = ["admit_strict_command", "pin_command_consumer", "check_worker_capability_clock"]
