"""Fenced, metadata-only ERP refusal receipts in the native idempotency journal.

A receipt proves non-execution of one command. It never grants execution authority.
"""

import json
from datetime import timedelta
from hashlib import sha256
from typing import Any as Any
from uuid import UUID

from agent_core.contracts.broker_envelope import PrincipalScope as PrincipalScope
from agent_core.contracts.broker_envelope import ZebraCommandEnvelope as ZebraCommandEnvelope
from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import EventId as EventId
from agent_core.domain.identifiers import SessionId as SessionId
from agent_core.domain.identifiers import TaskId as TaskId
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_storage.postgres.command_coverage_admission import _identity, pin_command_consumer
from agent_storage.postgres.command_wakeup import _scope_from_binding, command_scope_key
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.erp_fresh_disposition_evidence import (
    _binding_identity as _binding_identity,
)
from agent_storage.postgres.erp_fresh_disposition_evidence import (
    _modern as _read_modern_evidence,
)
from agent_storage.postgres.erp_fresh_disposition_evidence import (
    _turn as _read_turn_evidence,
)
from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.idempotency import save_idempotency_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary
from agent_storage.postgres.legacy_command_candidates import LEGACY_REJECTION_ACTION
from agent_storage.postgres.task_admission import read_session_task_binding
from agent_storage.postgres.task_event_positions import _lock_task
from agent_storage.postgres.worker_capability import (
    WorkerCapabilityLostError,
    check_worker_capability_clock,
)

ACTION = "worker.erp-fresh-disposition.v1"
REFUSED = "erp_fresh_authority_refused"
UNAVAILABLE = "erp_fresh_authority_unavailable"
EXHAUSTED = "erp_fresh_authority_retry_exhausted"
REASONS = {
    REFUSED: frozenset(
        {
            "grant_expired",
            "probe_expired",
            "prior_revocation",
            "host_identity_drift",
            "probe_rejected",
        }
    ),
    UNAVAILABLE: frozenset(
        {"probe_timeout", "probe_network_unavailable", "probe_http_unavailable"}
    ),
}
FENCE_FIELDS = ("control_plane_epoch", "fencing_token", "owner_instance_id")


def _command(connection, namespace, event_id):
    event = read_event_in_transaction(connection, namespace, EventId(UUID(str(event_id))))
    if event is None or event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
        raise ValueError("fresh disposition requires a canonical command")
    command = validate_accepted_session_command(
        event.payload, session_id=event.session_id, idempotency_key=event.idempotency_key
    )
    return event, command


def _proof_digest(body):
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fingerprint(event):
    return sha256(event.model_dump_json().encode()).hexdigest()


def _turn(connection, namespace, event, command, floor, input_event_id=None):
    return _read_turn_evidence(
        connection, namespace, event, command, floor, input_event_id, command_loader=_command
    )


def _modern(connection, namespace, event, pending, receipt, scope):
    return _read_modern_evidence(
        connection, namespace, event, pending, receipt, scope, fence_fields=FENCE_FIELDS
    )


def persist_fresh_disposition(
    dsn,
    namespace,
    lease: WorkerLease,
    *,
    code,
    reason,
    accepted_event: SessionEvent | None = None,
    consumer_capability=None,
):
    """Called only by the typed initial gate, INSIDE its live LeaseHeartbeat."""
    if namespace != "erpnext" or reason not in REASONS.get(code, ()):
        raise ValueError("invalid fresh disposition classification")
    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        modern = accepted_event is None
        if modern:
            rows = connection.execute(
                (
                    "SELECT accepted_event_id FROM command_handoff_receipts\n         "
                    "       WHERE deployment_namespace=%s AND session_id=%s AND statu"
                    "s='accepted'\n                  AND control_plane_epoch=%s AND fe"
                    "ncing_token=%s AND owner_instance_id=%s LIMIT 2"
                ),
                (namespace, lease.session_id, *(getattr(lease.fence, k) for k in FENCE_FIELDS)),
            ).fetchall()
            if len(rows) != 1:
                raise ValueError("fresh disposition requires one exact fenced handoff")
            event_id = rows[0]["accepted_event_id"]
        else:
            event_id = accepted_event.event_id
        capability = pin_command_consumer(connection, namespace, event_id, consumer_capability)
        lock_session_lease_boundary(connection, namespace, lease.session_id)
        assert_current_lease_fence(connection, namespace, lease.session_id, lease.fence)
        stream = connection.execute(
            (
                "SELECT current_version FROM session_streams WHERE deployment_nam"
                "espace=%s AND session_id=%s FOR UPDATE"
            ),
            (namespace, lease.session_id),
        ).fetchone()
        event, command = _command(connection, namespace, event_id)
        if event.session_id != lease.session_id or (
            accepted_event is not None and event != accepted_event
        ):
            raise ValueError("fresh disposition canonical Event changed")
        binding = read_session_task_binding(connection, namespace, lease.session_id)
        if binding is None:
            raise ValueError("fresh disposition stored binding is missing")
        identity = _binding_identity(binding, event, command)
        scope = _scope_from_binding(connection, namespace, event)
        pending = connection.execute(
            (
                "SELECT * FROM session_command_pending WHERE deployment_namespace"
                "=%s AND accepted_event_id=%s FOR UPDATE"
            ),
            (namespace, event_id),
        ).fetchone()
        receipt = connection.execute(
            (
                "SELECT * FROM command_handoff_receipts WHERE deployment_namespac"
                "e=%s AND accepted_event_id=%s FOR UPDATE"
            ),
            (namespace, event_id),
        ).fetchone()
        if modern:
            if pending is None:
                raise ValueError("fresh disposition pending identity is missing")
            outbox = _modern(connection, namespace, event, pending, receipt, scope)
            if any(str(receipt[k]) != str(getattr(lease.fence, k)) for k in FENCE_FIELDS):
                raise ValueError("fresh disposition handoff fence changed")
            floor, generation = receipt["execution_floor_sequence"], pending["current_generation"]
        else:
            if pending is not None or receipt is not None:
                raise ValueError("classic refusal cannot rewrite a modern command")
            floor, generation, outbox = stream["current_version"], 0, None
        if (
            stream is None
            or stream["current_version"] != floor
            or connection.execute(
                (
                    "SELECT 1 FROM session_events WHERE deployment_namespace=%s AND s"
                    "ession_id=%s AND event_type='session_command_accepted' AND seque"
                    "nce>%s LIMIT 1"
                ),
                (namespace, lease.session_id, event.sequence),
            ).fetchone()
            is not None
        ):
            raise ValueError("fresh disposition has a successor or post-floor evidence")
        turn = _turn(
            connection,
            namespace,
            event,
            command,
            floor,
            None if receipt is None else receipt["input_event_id"],
        )
        body = {
            "version": 1,
            "namespace": namespace,
            "mode": "modern" if modern else "classic",
            "accepted_event_id": str(event_id),
            "accepted_sequence": event.sequence,
            "session_id": str(event.session_id),
            "command_id": command.command_id,
            "event_fingerprint": _fingerprint(event),
            "command_fingerprint": command.fingerprint,
            "scope_key": command_scope_key(scope),
            **identity,
            **turn,
            "generation": generation,
            "floor": floor,
            "code": code,
            "reason": reason,
            "fence": lease.fence.model_dump(mode="json"),
            "envelope_digest": None if outbox is None else outbox["envelope_digest"],
        }
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        record = IdempotencyRecord(
            action=ACTION,
            idempotency_key=f"{event_id}:{generation}",
            request_hash=_fingerprint(event),
            status_code=409,
            response_body=body,
            created_at=now,
        )
        stored = save_idempotency_in_transaction(connection, namespace, record)
        if stored.response_body != body or stored.status_code != 409:
            raise ValueError("fresh disposition immutable proof conflicts")
        if modern:
            if pending["status"] not in ("pending", "dead") or (
                pending["status"] == "dead" and pending["recovery_code"] != code
            ):
                raise ValueError("fresh disposition pending state conflicts")
            connection.execute(
                (
                    "UPDATE session_command_pending SET status=%s,recovery_code=%s,re"
                    "covery_due_at=greatest(recovery_due_at,%s) WHERE deployment_name"
                    "space=%s AND accepted_event_id=%s"
                ),
                (
                    "pending" if code == UNAVAILABLE else "dead",
                    code,
                    now + timedelta(seconds=60),
                    namespace,
                    event_id,
                ),
            )
        else:
            rejection = IdempotencyRecord(
                action=LEGACY_REJECTION_ACTION,
                idempotency_key=str(event_id),
                request_hash=_fingerprint(event),
                status_code=409,
                created_at=now,
                response_body={
                    "status": "rejected",
                    "reason": code,
                    "accepted_event_id": str(event_id),
                    "session_id": str(event.session_id),
                    "fresh_proof_digest": _proof_digest(body),
                },
            )
            saved = save_idempotency_in_transaction(connection, namespace, rejection)
            if saved.response_body != rejection.response_body or saved.status_code != 409:
                raise ValueError("fresh disposition classic rejection conflicts")
        _lock_task(connection, namespace, TaskId(UUID(binding.task_id)), shared=True)
        current = read_session_task_binding(connection, namespace, lease.session_id)
        if current != binding:
            raise ValueError("fresh disposition Task binding changed")
        repinned = pin_command_consumer(
            connection, namespace, event_id, consumer_capability, lock_task_authority=True
        )
        if (capability is None) != (repinned is None):
            raise ValueError("fresh disposition strict requirement changed")
        if repinned is not None:
            check_worker_capability_clock(connection, repinned)
        assert_current_lease_fence(connection, namespace, lease.session_id, lease.fence)
        return body


def verified_fresh_disposition(connection, namespace, event_id, *, terminal=False):
    """Verify immutable historical proof; today's successor execution is irrelevant.

    Returns None for absent proof. Conflicting proof fails closed, never authorizes
    skipping an old command or exposing a retry action.
    """
    pending = connection.execute(
        (
            "SELECT * FROM session_command_pending WHERE deployment_namespace"
            "=%s AND accepted_event_id=%s"
        ),
        (namespace, event_id),
    ).fetchone()
    generation = 0 if pending is None else pending["current_generation"]
    row = connection.execute(
        (
            "SELECT * FROM control_plane_idempotency_records WHERE deployment"
            "_namespace=%s AND action=%s AND idempotency_key=%s"
        ),
        (namespace, ACTION, f"{event_id}:{generation}"),
    ).fetchone()
    if row is None:
        return None
    event, command = _command(connection, namespace, event_id)
    body = row["response_body"]
    if (
        not isinstance(body, dict)
        or namespace != "erpnext"
        or body.get("version") != 1
        or row["status_code"] != 409
        or row["request_hash"] != _fingerprint(event)
        or body.get("reason") not in REASONS.get(body.get("code"), ())
    ):
        raise ValueError("invalid fresh disposition proof")
    fence = body.get("fence")
    if (
        not isinstance(fence, dict)
        or set(fence) != set(FENCE_FIELDS)
        or LeaseFence.model_validate(fence).model_dump(mode="json") != fence
    ):
        raise ValueError("fresh disposition sealed fence is invalid")
    expected = {
        "namespace": namespace,
        "accepted_event_id": str(event_id),
        "accepted_sequence": event.sequence,
        "session_id": str(event.session_id),
        "command_id": command.command_id,
        "event_fingerprint": _fingerprint(event),
        "command_fingerprint": command.fingerprint,
        "generation": generation,
        "mode": "classic" if pending is None else "modern",
    }
    if any(body.get(k) != v for k, v in expected.items()):
        raise ValueError("fresh disposition canonical identity conflicts")
    snapshot = connection.execute(
        (
            "SELECT snapshot_json,binding_digest FROM task_binding_snapshots "
            "WHERE deployment_namespace=%s AND task_id=%s AND binding_revisio"
            "n=%s"
        ),
        (namespace, body.get("task_id"), body.get("binding_revision")),
    ).fetchone()
    if snapshot is None:
        raise ValueError("fresh disposition original binding is missing")
    binding = TaskBindingSnapshot.model_validate(snapshot["snapshot_json"])
    if snapshot["binding_digest"] != binding.binding_digest or any(
        body.get(k) != v for k, v in _binding_identity(binding, event, command).items()
    ):
        raise ValueError("fresh disposition original binding conflicts")
    # Current lineage and immutable scope must still agree; its new Run/expiry
    # does not invalidate the historical non-execution proof.
    current = read_session_task_binding(connection, namespace, event.session_id)
    scope = _scope_from_binding(connection, namespace, event)
    if (
        current is None
        or current.task_id != binding.task_id
        or body.get("scope_key") != command_scope_key(scope)
    ):
        raise ValueError("fresh disposition Task scope conflicts")
    floor = body.get("floor")
    if type(floor) is not int or floor < event.sequence:
        raise ValueError("fresh disposition invalid floor")
    receipt = connection.execute(
        (
            "SELECT * FROM command_handoff_receipts WHERE deployment_namespac"
            "e=%s AND accepted_event_id=%s"
        ),
        (namespace, event_id),
    ).fetchone()
    if pending is not None:
        outbox = _modern(connection, namespace, event, pending, receipt, scope)
        if (
            floor != receipt["execution_floor_sequence"]
            or body.get("envelope_digest") != outbox["envelope_digest"]
            or body.get("fence")
            != {
                k: receipt[k] if isinstance(receipt[k], int) else str(receipt[k])
                for k in FENCE_FIELDS
            }
        ):
            raise ValueError("fresh disposition accepted fence conflicts")
        if pending["recovery_code"] == EXHAUSTED:
            if pending["status"] != "dead" or body["code"] != UNAVAILABLE:
                raise ValueError("fresh disposition exhaustion conflicts")
        elif pending["recovery_code"] != body["code"] or pending["status"] != (
            "pending" if body["code"] == UNAVAILABLE else "dead"
        ):
            raise ValueError("fresh disposition pending outcome conflicts")
        if terminal and pending["status"] != "dead":
            return None
    else:
        rejection = connection.execute(
            (
                "SELECT * FROM control_plane_idempotency_records WHERE deployment"
                "_namespace=%s AND action=%s AND idempotency_key=%s"
            ),
            (namespace, LEGACY_REJECTION_ACTION, str(event_id)),
        ).fetchone()
        if (
            receipt is not None
            or body.get("envelope_digest") is not None
            or rejection is None
            or rejection["request_hash"] != _fingerprint(event)
            or rejection["status_code"] != 409
            or rejection["response_body"]
            != {
                "status": "rejected",
                "reason": body["code"],
                "accepted_event_id": str(event_id),
                "session_id": str(event.session_id),
                "fresh_proof_digest": _proof_digest(body),
            }
        ):
            raise ValueError("fresh disposition classic rejection conflicts")
    turn = _turn(
        connection,
        namespace,
        event,
        command,
        floor,
        None if receipt is None else receipt["input_event_id"],
    )
    if any(body.get(k) != v for k, v in turn.items()):
        raise ValueError("fresh disposition sealed Turn conflicts")
    later = connection.execute(
        (
            "SELECT event_id,sequence,event_type FROM session_events WHERE de"
            "ployment_namespace=%s AND session_id=%s AND sequence>%s ORDER BY"
            " sequence LIMIT 1"
        ),
        (namespace, event.session_id, floor),
    ).fetchone()
    if later is not None:
        if later["event_type"] != "session_command_accepted":
            raise ValueError("fresh disposition has execution before its successor")
        _command(connection, namespace, later["event_id"])
    return body


def fresh_retry_eligible(connection, namespace, body):
    """Current same-Turn eligibility, separate from permanent historical validity."""
    try:
        # Observation shares native strict identity/deadlines without row locks
        # in the header's read-only snapshot. Every execution pin keeps its lock.
        _identity(connection, namespace, UUID(body["session_id"]), lock_registry=False)
    except WorkerCapabilityLostError:
        return False
    if (
        connection.execute(
            (
                "SELECT 1 FROM session_events WHERE deployment_namespace=%s AND s"
                "ession_id=%s AND sequence>%s LIMIT 1"
            ),
            (namespace, body["session_id"], body["floor"]),
        ).fetchone()
        is not None
    ):
        return False
    return (
        connection.execute(
            """SELECT 1 FROM worker_leases l JOIN control_plane_epochs e USING(deployment_namespace)
        WHERE l.deployment_namespace=%s AND l.session_id=%s AND l.control_plane_epoch=e.epoch
          AND l.released_at IS NULL AND l.expires_at>clock_timestamp()""",
            (namespace, body["session_id"]),
        ).fetchone()
        is None
    )
