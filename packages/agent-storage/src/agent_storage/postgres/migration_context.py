"""Fail-closed replay of SQLite Context capsule authority into PostgreSQL."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agent_core.contracts.context_events import (
    ContextCapsuleCreatedPayload,
    ContextCompactedPayload,
)
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventType, SessionEvent
from psycopg.types.json import Jsonb

from agent_storage.postgres.migration_snapshot import SnapshotRecord


class ContextMigrationError(ValueError):
    """Raised when Context snapshot rows cannot be proven consistent."""


@dataclass(frozen=True, slots=True)
class ContextReplayReport:
    capsule_count: int
    active_count: int


def replay_context_snapshot(
    connection: Any,
    deployment_namespace: str,
    records_by_table: Mapping[str, Sequence[SnapshotRecord]],
    events: Mapping[UUID, SessionEvent],
) -> ContextReplayReport:
    """Import immutable capsules and active pointers after all Events exist."""
    capsule_records = records_by_table.get("context_capsule_artifacts", ())
    active_records = records_by_table.get("active_context_projections", ())
    if active_records and not capsule_records:
        raise ContextMigrationError("active Context pointer has no capsule source")

    capsules: dict[str, tuple[UUID, UUID, str]] = {}
    for record in capsule_records:
        values = _record_values(
            record,
            {
                "capsule_id",
                "artifact_id",
                "session_id",
                "payload",
                "payload_sha256",
                "source_hash",
                "created_at",
                "event_id",
            },
        )
        payload_bytes = _payload_bytes(values["payload"])
        payload_sha256 = _required_digest(values["payload_sha256"], "payload_sha256")
        if hashlib.sha256(payload_bytes).hexdigest() != payload_sha256:
            raise ContextMigrationError("Context capsule payload checksum failed")
        try:
            capsule = ContextCapsule.model_validate_json(payload_bytes)
            artifact_id = UUID(str(values["artifact_id"]))
            session_id = UUID(str(values["session_id"]))
            capsule_event_id = UUID(str(values["event_id"]))
        except (TypeError, ValueError) as error:
            raise ContextMigrationError("Context capsule row is malformed") from error
        capsule_event = events.get(capsule_event_id)
        if capsule_event is None:
            raise ContextMigrationError("Context capsule Event is missing")
        if capsule_event.event_type is not EventType.CONTEXT_CAPSULE_CREATED:
            raise ContextMigrationError("Context capsule row points to the wrong Event type")
        if capsule_event.session_id != session_id:
            raise ContextMigrationError("Context capsule session binding changed")
        _validate_created_event(capsule, artifact_id, capsule_event)
        compaction_event = _find_compaction_event(capsule_event, events)
        if compaction_event is None:
            raise ContextMigrationError("Context capsule compaction Event is missing")
        _validate_compaction_event(capsule, compaction_event)
        if str(values["capsule_id"]) != capsule.capsule_id:
            raise ContextMigrationError("Context capsule id binding changed")
        if str(values["source_hash"]) != capsule.source_hash:
            raise ContextMigrationError("Context capsule source hash changed")
        connection.execute(
            """INSERT INTO context_capsule_artifacts (
                deployment_namespace, capsule_id, artifact_id, session_id, payload,
                payload_sha256, source_hash, compaction_event_id, capsule_event_id,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                deployment_namespace,
                capsule.capsule_id,
                artifact_id,
                session_id,
                Jsonb(capsule.model_dump(mode="json")),
                payload_sha256,
                capsule.source_hash,
                compaction_event.event_id,
                capsule_event.event_id,
                values["created_at"],
            ),
        )
        capsules[capsule.capsule_id] = (session_id, artifact_id, capsule.source_hash)

    for record in active_records:
        values = _record_values(
            record,
            {
                "session_id",
                "capsule_id",
                "artifact_id",
                "source_hash",
                "event_sequence",
                "updated_at",
            },
        )
        try:
            session_id = UUID(str(values["session_id"]))
            artifact_id = UUID(str(values["artifact_id"]))
            event_sequence = _required_int(values["event_sequence"], "event_sequence")
        except (TypeError, ValueError) as error:
            raise ContextMigrationError("active Context pointer is malformed") from error
        capsule_id = str(values["capsule_id"])
        stored = capsules.get(capsule_id)
        if stored is None or stored[:2] != (session_id, artifact_id):
            raise ContextMigrationError("active Context pointer does not match its capsule")
        if stored[2] != str(values["source_hash"]):
            raise ContextMigrationError("active Context source hash changed")
        if not any(
            event.session_id == session_id and event.sequence == event_sequence
            for event in events.values()
        ):
            raise ContextMigrationError("active Context pointer Event is missing")
        connection.execute(
            """INSERT INTO active_context_projections (
                deployment_namespace, session_id, capsule_id, artifact_id,
                source_hash, event_sequence, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                deployment_namespace,
                session_id,
                capsule_id,
                artifact_id,
                values["source_hash"],
                event_sequence,
                values["updated_at"],
            ),
        )
    return ContextReplayReport(len(capsules), len(active_records))


def _record_values(record: SnapshotRecord, expected: set[str]) -> dict[str, object]:
    if set(record.columns) != expected or len(record.columns) != len(record.values):
        raise ContextMigrationError(f"unexpected {record.table} column contract")
    return dict(zip(record.columns, record.values, strict=True))


def _payload_bytes(value: object) -> bytes:
    if isinstance(value, dict) and set(value) == {"$bytes"}:
        encoded = value["$bytes"]
        if not isinstance(encoded, str):
            raise ContextMigrationError("Context capsule payload bytes are malformed")
        try:
            return base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ContextMigrationError("Context capsule payload bytes are malformed") from error
    if isinstance(value, str):
        return value.encode("utf-8")
    raise ContextMigrationError("Context capsule payload must be bytes")


def _required_digest(value: object, field: str) -> str:
    digest = str(value)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ContextMigrationError(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _required_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ContextMigrationError(f"{field} must be an integer")
    try:
        return int(value)
    except ValueError as error:
        raise ContextMigrationError(f"{field} must be an integer") from error


def _validate_created_event(
    capsule: ContextCapsule, artifact_id: UUID, event: SessionEvent
) -> None:
    try:
        payload = ContextCapsuleCreatedPayload.model_validate(event.payload)
    except ValueError as error:
        raise ContextMigrationError("Context capsule Event payload is malformed") from error
    if (
        payload.capsule_id != capsule.capsule_id
        or payload.schema_version != capsule.version
        or payload.source_hash != capsule.source_hash
        or payload.source_event_range != capsule.source_event_range
    ):
        raise ContextMigrationError("Context capsule Event binding changed")
    try:
        event_artifact_id = UUID(payload.artifact_id)
    except ValueError as error:
        raise ContextMigrationError("Context capsule artifact id is malformed") from error
    if event_artifact_id != artifact_id:
        raise ContextMigrationError("Context capsule artifact binding changed")


def _find_compaction_event(
    capsule_event: SessionEvent, events: Mapping[UUID, SessionEvent]
) -> SessionEvent | None:
    return next(
        (
            event
            for event in events.values()
            if event.session_id == capsule_event.session_id
            and event.sequence == capsule_event.sequence - 1
            and event.event_type is EventType.CONTEXT_COMPACTED
        ),
        None,
    )


def _validate_compaction_event(capsule: ContextCapsule, event: SessionEvent) -> None:
    try:
        payload = ContextCompactedPayload.model_validate(event.payload)
    except ValueError as error:
        raise ContextMigrationError("Context compaction Event payload is malformed") from error
    if payload.capsule is not None and payload.capsule != capsule:
        raise ContextMigrationError("Context compaction capsule binding changed")
