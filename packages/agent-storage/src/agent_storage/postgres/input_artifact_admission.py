"""Input metadata shares the exact admission/message transaction, never a Worker lease."""

from typing import Any
from uuid import UUID

from agent_core.application.session_attachments import attachment_refs_from_event
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.cloud_artifact_requests import canonical_artifact_reserve_hash
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import Session
from agent_core.domain.task_bindings import TaskBindingSnapshot

from agent_storage.event_rows import SessionEventSequenceConflictError
from agent_storage.postgres.artifact_payload_transaction_support import hash_text
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.task_admission import save_task_binding_in_transaction
from agent_storage.postgres.task_control_target import require_task_control_target
from agent_storage.postgres.workspaces import (
    get_workspace_in_transaction,
    save_workspace_in_transaction,
)


def persist_input_artifacts(
    connection: Any,
    namespace: str,
    events: tuple[SessionEvent, ...],
    records: tuple[CloudArtifactPayloadRecord, ...],
) -> None:
    materializations = {
        e.event_id: e for e in events if e.event_type is EventType.INPUT_ARTIFACT_STORED
    }
    if not records and not materializations:
        return
    references = {ref.attachment_id: ref for e in events for ref in attachment_refs_from_event(e)}
    if len(records) != len(materializations) or len({r.artifact_id for r in records}) != len(
        records
    ):
        raise ValueError("input publication is not a complete unique batch")
    epoch = connection.execute(
        "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s FOR SHARE",
        (namespace,),
    ).fetchone()
    if epoch is None:
        raise ValueError("input admission requires current control-plane epoch")
    for record in records:
        binding, receipt, reservation = (
            record.event_binding,
            record.object_receipt,
            record.reservation,
        )
        event = materializations.get(binding.event_id) if binding is not None else None
        ref = references.get(record.artifact_id)
        if (
            record.deployment_namespace != namespace
            or record.lifecycle_status != "finalized"
            or receipt is None
            or binding is None
            or event is None
            or ref is None
            or event.session_id != record.session_id
            or event.sequence != binding.sequence
            or ref.message_event_id != event.causation_id
            or event.payload.get("uri") != record.uri
            or event.payload.get("sha256") != reservation.sha256
            or event.payload.get("size_bytes") != reservation.size_bytes
            or ref.sha256 != reservation.sha256
            or ref.size_bytes != reservation.size_bytes
        ):
            raise ValueError("input metadata is outside its exact admitted message")
        # This fence records the actual epoch + admitted event revision. It is an
        # API CAS owner, never a fabricated Worker lease or mutable local payload.
        connection.execute(
            """INSERT INTO artifact_payload_metadata (
            deployment_namespace,artifact_id,session_id,intended_event_sequence,expected_stream_revision,
            kind,mime_type,sha256,size_bytes,idempotency_key,idempotency_key_hash,request_hash,file_name,
            retained_until,reservation_epoch,reservation_fencing_token,reservation_owner_instance_id,
            lifecycle_status,lifecycle_revision,object_version,object_verified_at,event_id,event_sequence,
            artifact_uri,finalized_at,request_created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'finalized',2,%s,%s,%s,%s,%s,transaction_timestamp(),%s)""",
            (
                namespace,
                record.artifact_id,
                record.session_id,
                binding.sequence,
                binding.sequence - 1,
                reservation.kind,
                reservation.mime_type,
                reservation.sha256,
                reservation.size_bytes,
                reservation.idempotency_key,
                hash_text(reservation.idempotency_key),
                canonical_artifact_reserve_hash(namespace, reservation),
                reservation.file_name,
                reservation.retained_until,
                epoch["epoch"],
                binding.sequence + 1,
                "api-input:" + str(binding.event_id),
                receipt.object_version,
                receipt.verified_at,
                binding.event_id,
                binding.sequence,
                record.uri,
                reservation.created_at,
            ),
        )


def append_input_message(
    dsn: str,
    namespace: str,
    session: Session,
    events: tuple[SessionEvent, ...],
    records: tuple[CloudArtifactPayloadRecord, ...],
    *,
    release_binding: TaskBindingSnapshot | None = None,
) -> Session:
    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        stream = connection.execute(
            "SELECT current_version FROM session_streams "
            "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
            (namespace, session.session_id),
        ).fetchone()
        if stream is None or stream["current_version"] != session.current_sequence:
            raise SessionEventSequenceConflictError("input message lost its stream CAS")
        workspace = get_workspace_in_transaction(connection, namespace, session.session_id)
        if release_binding is not None:
            task_id = TaskId(UUID(release_binding.task_id))
            require_task_control_target(
                connection, namespace, task_id, session.session_id, replay=False
            )
            snapshot = events[0].payload.get("definition_snapshot")
            if (
                events[0].event_type is not EventType.USER_MESSAGE_RECEIVED
                or not isinstance(snapshot, dict)
                or snapshot.get("snapshot_digest")
                != release_binding.agent_capability_ceiling.definition_snapshot_digest
                or release_binding.binding_revision < 2
            ):
                raise ValueError("message release snapshot differs from its authorization")
            save_task_binding_in_transaction(
                connection,
                namespace,
                release_binding,
                expected_previous_revision=release_binding.binding_revision - 1,
            )
        for event in events:
            append_event_in_transaction(connection, namespace, event)
            session = apply_event(session, event)
            if workspace is not None:
                workspace = apply_workspace(workspace, event)
        persist_input_artifacts(connection, namespace, events, records)
        save_session_in_transaction(connection, namespace, session)
        if workspace is not None:
            save_workspace_in_transaction(connection, namespace, workspace)
    return session
