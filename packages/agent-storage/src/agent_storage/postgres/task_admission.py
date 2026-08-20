"""PostgreSQL atomic Task admission (AL-TASK-ADMISSION-PG-01).

One transaction persists bootstrap Events, the Session and Workspace
projections, the Agent Task row with its event index, the immutable Task
binding snapshot and the idempotency receipt. Every helper used here runs
in the caller's transaction, so any injected failure rolls the whole
admission back — no half-accepted Task survives.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import (
    TaskAdmissionIdempotencyConflict,
    TaskAdmissionReceipt,
    TaskAdmissionRequest,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.task_index_transactions import rebuild_task_in_transaction
from agent_storage.postgres.workspaces import save_workspace_in_transaction


class PostgresTaskAdmissionTransaction:
    """Admit a Task atomically over the v25 schema."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def admit(self, request: TaskAdmissionRequest) -> TaskAdmissionReceipt:
        request.validate()
        with self._database.connect() as connection:
            return self.admit_in_transaction(
                connection, self.deployment_namespace, request
            )

    def admit_in_transaction(
        self,
        connection: Any,
        namespace: str,
        request: TaskAdmissionRequest,
    ) -> TaskAdmissionReceipt:
        """Run the full admission inside the CALLER's transaction.

        The durable delegation store uses this to materialize the child
        Task and its delegation link in one commit — no orphan child can
        survive a crash between the two writes.
        """

        request.validate()
        if request.idempotency is not None:
            replayed = _insert_or_load_idempotency(
                connection,
                namespace,
                request.idempotency,
            )
            if replayed is not None:
                if replayed.request_hash != request.idempotency.request_hash:
                    raise TaskAdmissionIdempotencyConflict(
                        "idempotency key reused with a different request"
                    )
                return TaskAdmissionReceipt(
                    task_id=TaskId(UUID(str(request.events[0].session_id))),
                    session_id=request.session.session_id,
                    event_count=0,
                    binding_digest=None,
                    idempotent_replay=True,
                    replayed_record=replayed,
                )
        persisted_events = tuple(
            append_event_in_transaction(connection, namespace, event)
            for event in request.events
        )
        save_session_in_transaction(connection, namespace, request.session)
        save_workspace_in_transaction(connection, namespace, request.workspace)
        root_session_id = SessionId(UUID(str(persisted_events[0].session_id)))
        task = rebuild_task_in_transaction(connection, namespace, root_session_id)
        binding_digest: str | None = None
        if request.binding is not None:
            binding_digest = _insert_binding_snapshot(
                connection,
                namespace,
                request.binding,
            )
        return TaskAdmissionReceipt(
            task_id=task.task_id,
            session_id=root_session_id,
            event_count=len(persisted_events),
            binding_digest=binding_digest,
        )



def update_idempotency_response(
    dsn: str,
    *,
    deployment_namespace: str,
    action: str,
    idempotency_key: str,
    response_body: dict[str, object],
) -> bool:
    """Replace the stored response body after post-admission composition.

    The admission transaction stores the receipt atomically as a claim
    (so a duplicate create can never slip through); composition steps
    that legitimately extend the 201 body afterwards (run-command
    queueing) sync the stored replay body with this update. A crash
    before the update replays the pre-command body — still honest.
    """

    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        updated = connection.execute(
            """
            UPDATE control_plane_idempotency_records
            SET response_body = %s
            WHERE deployment_namespace = %s AND action = %s AND idempotency_key = %s
            """,
            (Jsonb(response_body), deployment_namespace, action, idempotency_key),
        ).rowcount
    return updated > 0


def save_task_binding(
    dsn: str,
    *,
    deployment_namespace: str,
    binding: TaskBindingSnapshot,
) -> str:
    """Persist one immutable binding snapshot outside a full admission.

    Phase F3: the cloud create path freezes the Task binding right after
    session creation so the Worker's binding-aware authority (F1) and the
    pinned egress (F2) can consume it. Revision conflicts fail closed.
    """

    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        existing = connection.execute(
            """
            SELECT binding_digest FROM task_binding_snapshots
            WHERE deployment_namespace = %s AND task_id = %s
                AND binding_revision = %s
            """,
            (
                deployment_namespace,
                str(binding.task_id),
                binding.binding_revision,
            ),
        ).fetchone()
        if existing is not None:
            if existing["binding_digest"] != binding.binding_digest:
                raise ValueError(
                    "task binding revision is immutable and already exists "
                    "with a different digest"
                )
            return binding.binding_digest
        _insert_binding_snapshot(connection, deployment_namespace, binding)
    return binding.binding_digest

def _insert_or_load_idempotency(
    connection: Any,
    namespace: str,
    receipt: IdempotencyRecord,
) -> IdempotencyRecord | None:
    """Return the existing receipt when the key already committed."""

    existing = connection.execute(
        """
        SELECT action, idempotency_key, request_hash, status_code,
               response_body, created_at
        FROM control_plane_idempotency_records
        WHERE deployment_namespace = %s AND action = %s AND idempotency_key = %s
        """,
        (namespace, receipt.action, receipt.idempotency_key),
    ).fetchone()
    if existing is not None:
        return IdempotencyRecord(
            action=existing["action"],
            idempotency_key=existing["idempotency_key"],
            request_hash=existing["request_hash"],
            status_code=existing["status_code"],
            response_body=dict(existing["response_body"]),
            created_at=existing["created_at"],
        )
    connection.execute(
        """
        INSERT INTO control_plane_idempotency_records (
            deployment_namespace, action, idempotency_key, request_hash,
            status_code, response_body, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            namespace,
            receipt.action,
            receipt.idempotency_key,
            receipt.request_hash,
            receipt.status_code,
            Jsonb(receipt.response_body),
            receipt.created_at,
        ),
    )
    return None


def _insert_binding_snapshot(
    connection: Any,
    namespace: str,
    binding: TaskBindingSnapshot,
) -> str:
    connection.execute(
        """
        INSERT INTO task_binding_snapshots (
            deployment_namespace, task_id, binding_revision, binding_digest,
            definition_snapshot_digest, host_manifest_digest,
            connector_profile_digest, grant_digest, snapshot_json,
            effective_capabilities, bound_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            namespace,
            str(binding.task_id),
            binding.binding_revision,
            binding.binding_digest,
            binding.agent_capability_ceiling.definition_snapshot_digest,
            binding.host_capability.manifest_digest,
            binding.host_capability.connector_profile_digest,
            binding.host_capability.grant_digest,
            Jsonb(_binding_json(binding)),
            Jsonb(sorted(binding.effective_capabilities)),
            binding.bound_at,
        ),
    )
    return binding.binding_digest


def _binding_json(binding: TaskBindingSnapshot) -> dict[str, object]:
    """Full model dump — the snapshot must round-trip through validate()."""

    return binding.model_dump(mode="json")

def load_task_binding(
    dsn: str,
    *,
    deployment_namespace: str,
    task_id: TaskId,
) -> TaskBindingSnapshot | None:
    """Reconstruct the latest immutable binding snapshot for one Task."""

    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT snapshot_json FROM task_binding_snapshots
            WHERE deployment_namespace = %s AND task_id = %s
            ORDER BY binding_revision DESC
            LIMIT 1
            """,
            (deployment_namespace, str(task_id)),
        ).fetchone()
    if row is None:
        return None
    binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
    if binding.binding_digest != _binding_digest_of(binding):
        raise ValueError("stored task binding digest does not match its snapshot")
    return binding


def _binding_digest_of(binding: TaskBindingSnapshot) -> str:
    return binding.binding_digest
