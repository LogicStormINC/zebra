"""Fail-closed replay of SQLite Session Handoff state into PostgreSQL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.session_handoff import (
    HandoffOperationStatus,
    SessionHandoffEnvelope,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.migration_handoff_rows import (
    HandoffMigrationError,
    parse_dispatch,
    parse_envelope,
    parse_lineage,
    parse_operation,
)
from agent_storage.postgres.migration_snapshot import SnapshotRecord

__all__ = [
    "HandoffMigrationError",
    "HandoffReplayReport",
    "replay_handoff_snapshot",
    "validate_rebuilt_handoff_lineage",
]


@dataclass(frozen=True, slots=True)
class HandoffReplayReport:
    operation_count: int
    envelope_count: int
    dispatch_count: int
    lineage_count: int


def replay_handoff_snapshot(
    connection: Any,
    deployment_namespace: str,
    records_by_table: Mapping[str, Sequence[SnapshotRecord]],
    events: Mapping[UUID, SessionEvent],
) -> HandoffReplayReport:
    """Replay Handoff authority after Events exist and before Task validation."""
    operations = tuple(
        parse_operation(record) for record in records_by_table.get("handoff_operations", ())
    )
    operation_by_id = {row["operation_id"]: row for row in operations}
    if len(operation_by_id) != len(operations):
        raise HandoffMigrationError("Handoff operation ids are duplicated")
    envelopes = tuple(
        parse_envelope(record)
        for record in records_by_table.get("session_handoff_envelopes", ())
    )
    envelope_by_id = {row["handoff_id"]: row for row in envelopes}
    if len(envelope_by_id) != len(envelopes):
        raise HandoffMigrationError("Handoff envelope ids are duplicated")
    dispatches = tuple(
        parse_dispatch(record)
        for record in records_by_table.get("handoff_dispatch_outbox", ())
    )
    lineages = tuple(
        parse_lineage(record)
        for record in records_by_table.get("session_lineage", ())
    )
    _validate_relations(operations, envelope_by_id, dispatches, lineages, events)
    for row in operations:
        workspace = cast(Any, row["workspace_revision"])
        connection.execute(
            """INSERT INTO handoff_operations (
                deployment_namespace, operation_id, status, source_session_id,
                target_session_id, handoff_id, idempotency_key_hash, request_hash,
                expected_source_stream_version, source_lease_epoch,
                source_lease_fencing_token, source_lease_owner_instance_id,
                authority_revision, workspace_revision, task_profile_revision,
                effective_depth_limit, artifact_id, created_at, updated_at, abort_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                deployment_namespace,
                row["operation_id"], row["status"], row["source_session_id"],
                row["target_session_id"], row["handoff_id"], row["idempotency_key_hash"],
                row["request_hash"], row["expected_source_stream_version"],
                row["source_lease_epoch"], row["source_lease_fencing_token"],
                row["source_lease_owner_instance_id"], row["authority_revision"],
                Jsonb(workspace.model_dump(mode="json")), row["task_profile_revision"],
                row["effective_depth_limit"], row["artifact_id"], row["created_at"],
                row["updated_at"], row["abort_code"],
            ),
        )
    for row in envelopes:
        envelope = cast(SessionHandoffEnvelope, row["envelope"])
        connection.execute(
            """INSERT INTO session_handoff_envelopes (
                deployment_namespace, handoff_id, source_session_id,
                target_session_id, artifact_id, envelope, checksum, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                deployment_namespace, row["handoff_id"], row["source_session_id"],
                row["target_session_id"], row["artifact_id"],
                Jsonb(envelope.model_dump(mode="json")), row["checksum"], envelope.created_at,
            ),
        )
    for row in dispatches:
        connection.execute(
            """INSERT INTO handoff_dispatch_outbox (
                deployment_namespace, delivery_id, child_session_id, handoff_id,
                status, claim_token, claim_epoch, claim_fencing_token,
                claim_owner_instance_id, claim_expires_at, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                deployment_namespace, row["delivery_id"], row["child_session_id"],
                row["handoff_id"], row["status"], row["claim_token"], row["claim_epoch"],
                row["claim_fencing_token"], row["claim_owner_instance_id"],
                row["claim_expires_at"], row["created_at"],
            ),
        )
    return HandoffReplayReport(
        operation_count=len(operations), envelope_count=len(envelopes),
        dispatch_count=len(dispatches), lineage_count=len(lineages),
    )


def validate_rebuilt_handoff_lineage(
    connection: Any,
    deployment_namespace: str,
    records_by_table: Mapping[str, Sequence[SnapshotRecord]],
) -> int:
    """Compare SQLite lineage read-model rows with rebuilt PostgreSQL segments."""
    source: dict[UUID, dict[str, object]] = {}
    for record in records_by_table.get("session_lineage", ()):
        item = parse_lineage(record)
        session_id = cast(UUID, item["session_id"])
        if session_id in source:
            raise HandoffMigrationError("Session lineage ids are duplicated")
        source[session_id] = item
    roots = {
        cast(UUID, item["root_session_id"])
        for item in source.values()
    }
    if not roots:
        return 0
    rows = connection.execute(
        """SELECT session_id, task_id, predecessor_id, segment_index
        FROM execution_segments
        WHERE deployment_namespace = %s AND task_id = ANY(%s)
        ORDER BY task_id, segment_index""",
        (deployment_namespace, list(roots)),
    ).fetchall()
    rebuilt = {
        UUID(str(row["session_id"])): (
            UUID(str(row["task_id"])),
            None if row["predecessor_id"] is None else UUID(str(row["predecessor_id"])),
            int(row["segment_index"]),
        )
        for row in rows
    }
    if len(rebuilt) != len(rows) or set(rebuilt) != set(source):
        raise HandoffMigrationError("rebuilt Task lineage differs from SQLite lineage")
    for session_id, item in source.items():
        expected = (
            cast(UUID, item["root_session_id"]),
            cast(UUID | None, item["parent_session_id"]),
            cast(int, item["stage_index"]),
        )
        if rebuilt[session_id] != expected:
            raise HandoffMigrationError("rebuilt Task lineage row changed")
    return len(source)


def _validate_relations(
    operations: Sequence[dict[str, object]],
    envelopes: Mapping[object, dict[str, object]],
    dispatches: Sequence[dict[str, object]],
    lineages: Sequence[dict[str, object]],
    events: Mapping[UUID, SessionEvent],
) -> None:
    operation_by_handoff = {item["handoff_id"]: item for item in operations}
    if len(operation_by_handoff) != len(operations):
        raise HandoffMigrationError("Handoff ids are duplicated")
    lineage_by_session = {item["session_id"]: item for item in lineages}
    if len(lineage_by_session) != len(lineages):
        raise HandoffMigrationError("Session lineage ids are duplicated")
    if lineages and not operations:
        raise HandoffMigrationError("Session lineage has no Handoff operation")
    for operation in operations:
        envelope = envelopes.get(operation["handoff_id"])
        if operation["status"] == HandoffOperationStatus.COMMITTED.value:
            if envelope is None or envelope["artifact_id"] != operation["artifact_id"]:
                raise HandoffMigrationError("committed Handoff envelope is missing")
            typed_envelope = cast(SessionHandoffEnvelope, envelope["envelope"])
            if not (
                cast(Any, operation["created_at"])
                <= typed_envelope.created_at
                <= cast(Any, operation["updated_at"])
            ):
                raise HandoffMigrationError("Handoff envelope timestamp is outside operation")
            if typed_envelope.target_stage_index > cast(int, operation["effective_depth_limit"]):
                raise HandoffMigrationError("Handoff envelope exceeds operation depth limit")
            _validate_events(operation, typed_envelope, events)
        elif envelope is not None:
            raise HandoffMigrationError("non-committed Handoff has an envelope")
    for handoff_id in envelopes:
        if handoff_id not in operation_by_handoff:
            raise HandoffMigrationError("Handoff envelope has no operation")
    for lineage in lineages:
        inbound = lineage["inbound_handoff_id"]
        if inbound is None:
            continue
        lineage_operation = operation_by_handoff.get(inbound)
        if (
            lineage_operation is None
            or lineage_operation["target_session_id"] != lineage["session_id"]
        ):
            raise HandoffMigrationError("Session lineage Handoff binding changed")
    dispatch_children: set[object] = set()
    for dispatch in dispatches:
        matched_operation = operation_by_handoff.get(dispatch["handoff_id"])
        if (
            matched_operation is None
            or matched_operation["status"] != HandoffOperationStatus.COMMITTED.value
        ):
            raise HandoffMigrationError("dispatch has no committed Handoff")
        if dispatch["child_session_id"] != matched_operation["target_session_id"]:
            raise HandoffMigrationError("dispatch child binding changed")
        if dispatch["child_session_id"] in dispatch_children:
            raise HandoffMigrationError("dispatch child ids are duplicated")
        dispatch_children.add(dispatch["child_session_id"])
    committed = {
        item["handoff_id"] for item in operations
        if item["status"] == HandoffOperationStatus.COMMITTED.value
    }
    if committed != set(envelopes) or committed != {item["handoff_id"] for item in dispatches}:
        raise HandoffMigrationError("committed Handoff aggregate is incomplete")
    for operation in operations:
        if operation["status"] == HandoffOperationStatus.COMMITTED.value and (
            operation["source_session_id"] not in lineage_by_session
            or operation["target_session_id"] not in lineage_by_session
        ):
            raise HandoffMigrationError("committed Handoff lineage is incomplete")


def _validate_events(
    operation: dict[str, object],
    envelope: SessionHandoffEnvelope,
    events: Mapping[UUID, SessionEvent],
) -> None:
    parent = _find_event(
        events, operation["source_session_id"], EventType.SESSION_HANDOFF_COMMITTED,
        operation["handoff_id"],
    )
    child = _find_event(
        events, operation["target_session_id"], EventType.SESSION_HANDOFF_RECEIVED,
        operation["handoff_id"],
    )
    if parent is None or child is None:
        raise HandoffMigrationError("committed Handoff Event binding is missing")
    if parent.sequence != cast(int, operation["expected_source_stream_version"]) + 1:
        raise HandoffMigrationError("committed Handoff source sequence changed")
    parent_payload, child_payload = parent.payload, child.payload
    if (
        parent_payload.get("target_session_id") != str(operation["target_session_id"])
        or parent_payload.get("artifact_id") != operation["artifact_id"]
        or parent_payload.get("checksum") != envelope.checksum
        or parent_payload.get("target_stage_index") != envelope.target_stage_index
        or parent_payload.get("source_event_hash") != envelope.source_event_hash
        or parent_payload.get("source_event_range")
        != envelope.source_event_range.model_dump(mode="json")
        or child_payload.get("parent_session_id") != str(operation["source_session_id"])
        or child_payload.get("root_session_id") != str(envelope.root_session_id)
        or child_payload.get("stage_index") != envelope.target_stage_index
        or child_payload.get("artifact_id") != operation["artifact_id"]
        or child_payload.get("checksum") != envelope.checksum
    ):
        raise HandoffMigrationError("Handoff Event payload binding changed")


def _find_event(
    events: Mapping[UUID, SessionEvent],
    session_id: object,
    event_type: EventType,
    handoff_id: object,
) -> SessionEvent | None:
    matches = tuple(
        event for event in events.values()
        if event.session_id == session_id
        and event.event_type is event_type
        and event.payload.get("handoff_id") == str(handoff_id)
    )
    if len(matches) > 1:
        raise HandoffMigrationError("Handoff Event binding is duplicated")
    return matches[0] if matches else None
