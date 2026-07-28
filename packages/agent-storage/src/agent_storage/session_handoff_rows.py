import hashlib
import sqlite3
from datetime import datetime
from uuid import UUID

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.session_handoff import (
    HandoffOperationStatus,
    SessionLineage,
    WorkspaceBindingRevision,
)
from agent_core.ports.session_handoff import HandoffOperation

from agent_storage.event_rows import serialize_event_payload


class HandoffStorageConflictError(ValueError):
    """Raised when a handoff cannot satisfy its durable reservation."""


class HandoffIdempotencyConflictError(HandoffStorageConflictError):
    """Raised when a key is reused for a different handoff request."""


def insert_event(connection: sqlite3.Connection, event: SessionEvent) -> None:
    connection.execute(
        "INSERT INTO session_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(event.event_id),
            str(event.session_id),
            event.sequence,
            event.event_type.value,
            serialize_event_payload(event.payload),
            event.actor.value,
            event.created_at.isoformat(),
            str(event.causation_id) if event.causation_id else None,
            str(event.correlation_id) if event.correlation_id else None,
            event.idempotency_key,
            event.policy_version,
            event.model_profile,
        ),
    )


def operation_from_row(row: sqlite3.Row) -> HandoffOperation:
    return HandoffOperation(
        operation_id=row["operation_id"],
        status=HandoffOperationStatus(row["status"]),
        source_session_id=SessionId(UUID(row["source_session_id"])),
        target_session_id=SessionId(UUID(row["target_session_id"])),
        handoff_id=HandoffId(UUID(row["handoff_id"])),
        idempotency_key_hash=row["idempotency_key_hash"],
        request_hash=row["request_hash"],
        expected_source_stream_version=row["expected_source_stream_version"],
        source_lease_fencing_token=row["source_lease_fencing_token"],
        authority_revision=row["authority_revision"],
        workspace_revision=WorkspaceBindingRevision.model_validate_json(row["workspace_revision"]),
        task_profile_revision=row["task_profile_revision"],
        effective_depth_limit=row["effective_depth_limit"],
        artifact_id=row["artifact_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        abort_code=row["abort_code"],
    )


def operation_values(operation: HandoffOperation) -> tuple[object, ...]:
    return (
        operation.operation_id,
        operation.status.value,
        str(operation.source_session_id),
        str(operation.target_session_id),
        str(operation.handoff_id),
        operation.idempotency_key_hash,
        operation.request_hash,
        operation.expected_source_stream_version,
        operation.source_lease_fencing_token,
        operation.authority_revision,
        operation.workspace_revision.model_dump_json(),
        operation.task_profile_revision,
        operation.effective_depth_limit,
        operation.artifact_id,
        operation.created_at.isoformat(),
        operation.updated_at.isoformat(),
        operation.abort_code,
    )


def lineage_from_row(row: sqlite3.Row) -> SessionLineage:
    return SessionLineage.model_validate(
        {
            "session_id": row["session_id"],
            "root_session_id": row["root_session_id"],
            "parent_session_id": row["parent_session_id"],
            "inbound_handoff_id": row["inbound_handoff_id"],
            "stage_index": row["stage_index"],
        }
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS handoff_operations (
    operation_id TEXT PRIMARY KEY, status TEXT NOT NULL, source_session_id TEXT NOT NULL,
    target_session_id TEXT NOT NULL UNIQUE, handoff_id TEXT NOT NULL UNIQUE,
    idempotency_key_hash TEXT NOT NULL, request_hash TEXT NOT NULL,
    expected_source_stream_version INTEGER NOT NULL, source_lease_fencing_token INTEGER,
    authority_revision TEXT NOT NULL, workspace_revision TEXT NOT NULL,
    task_profile_revision TEXT NOT NULL, effective_depth_limit INTEGER NOT NULL,
    artifact_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, abort_code TEXT,
    UNIQUE(source_session_id, idempotency_key_hash)
);
CREATE TABLE IF NOT EXISTS session_handoff_envelopes (
    handoff_id TEXT PRIMARY KEY, source_session_id TEXT NOT NULL, target_session_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL UNIQUE, envelope_json TEXT NOT NULL, checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_lineage (
    session_id TEXT PRIMARY KEY, root_session_id TEXT NOT NULL, parent_session_id TEXT,
    inbound_handoff_id TEXT UNIQUE, stage_index INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_lineage_successor
ON session_lineage(parent_session_id) WHERE parent_session_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS handoff_dispatch_outbox (
    delivery_id TEXT PRIMARY KEY, child_session_id TEXT NOT NULL UNIQUE, handoff_id TEXT NOT NULL,
    status TEXT NOT NULL, claimed_by TEXT, claim_expires_at TEXT, created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS immutable_handoff_envelope_update
BEFORE UPDATE ON session_handoff_envelopes BEGIN
    SELECT RAISE(ABORT, 'immutable handoff envelope');
END;
CREATE TRIGGER IF NOT EXISTS immutable_handoff_envelope_delete
BEFORE DELETE ON session_handoff_envelopes BEGIN
    SELECT RAISE(ABORT, 'immutable handoff envelope');
END;
"""
