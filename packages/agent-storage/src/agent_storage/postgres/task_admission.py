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
        namespace = self.deployment_namespace
        idempotent_replay = False
        with self._database.connect() as connection:
            if request.idempotency is not None:
                replayed = _insert_or_load_idempotency(
                    connection,
                    namespace,
                    request.idempotency,
                )
                if replayed is not None:
                    return TaskAdmissionReceipt(
                        task_id=TaskId(UUID(str(request.events[0].session_id))),
                        session_id=request.session.session_id,
                        event_count=0,
                        binding_digest=None,
                        idempotent_replay=True,
                    )
                idempotent_replay = False
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
            idempotent_replay=idempotent_replay,
        )


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
    return {
        "hostCapability": binding.host_capability.model_dump(mode="json"),
        "agentCapabilityCeiling": binding.agent_capability_ceiling.model_dump(
            mode="json"
        ),
        "zebraPolicyDigest": binding.zebra_policy_digest,
    }
