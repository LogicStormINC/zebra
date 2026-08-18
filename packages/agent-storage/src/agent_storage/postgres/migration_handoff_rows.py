"""Validated source-row decoders for Handoff migration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.session_handoff import (
    HandoffOperationStatus,
    SessionHandoffEnvelope,
    SessionLineage,
    WorkspaceBindingRevision,
)

from agent_storage.postgres.migration_snapshot import SnapshotRecord


class HandoffMigrationError(ValueError):
    """Raised when Handoff rows cannot be proven consistent."""


def parse_operation(record: SnapshotRecord) -> dict[str, object]:
    values = _record_values(record, {
        "operation_id", "status", "source_session_id", "target_session_id", "handoff_id",
        "idempotency_key_hash", "request_hash", "expected_source_stream_version",
        "source_lease_fencing_token", "source_lease_epoch", "source_lease_owner_instance_id",
        "authority_revision", "workspace_revision", "task_profile_revision",
        "effective_depth_limit", "artifact_id", "created_at", "updated_at", "abort_code",
    })
    operation_id = _uuid(values["operation_id"], "operation_id")
    source_session_id = _uuid(values["source_session_id"], "source_session_id")
    target_session_id = _uuid(values["target_session_id"], "target_session_id")
    handoff_id = _uuid(values["handoff_id"], "handoff_id")
    status = str(values["status"])
    if status not in {item.value for item in HandoffOperationStatus}:
        raise HandoffMigrationError("Handoff operation status is unsupported")
    stream_version = _integer(values["expected_source_stream_version"], "stream version")
    depth = _integer(values["effective_depth_limit"], "depth limit")
    if stream_version < 0 or not 1 <= depth <= 128:
        raise HandoffMigrationError("Handoff operation bounds are invalid")
    workspace = _workspace(values["workspace_revision"])
    created_at = _timestamp(values["created_at"], "created_at")
    updated_at = _timestamp(values["updated_at"], "updated_at")
    if created_at > updated_at:
        raise HandoffMigrationError("Handoff operation timestamps are reversed")
    lease = _lease(values)
    idempotency_key_hash = _digest(values["idempotency_key_hash"], "idempotency_key_hash")
    request_hash = _digest(values["request_hash"], "request_hash")
    artifact_id = _optional_text(values["artifact_id"], "artifact_id")
    abort_code = _optional_text(values["abort_code"], "abort_code")
    if status == HandoffOperationStatus.PREPARING.value and (artifact_id or abort_code):
        raise HandoffMigrationError("preparing Handoff has terminal fields")
    if status == HandoffOperationStatus.COMMITTED.value and (not artifact_id or abort_code):
        raise HandoffMigrationError("committed Handoff has invalid terminal fields")
    if status == HandoffOperationStatus.ABORTED.value and (artifact_id or not abort_code):
        raise HandoffMigrationError("aborted Handoff has invalid terminal fields")
    return {
        "operation_id": operation_id,
        "status": status,
        "source_session_id": source_session_id,
        "target_session_id": target_session_id,
        "handoff_id": handoff_id,
        "idempotency_key_hash": idempotency_key_hash,
        "request_hash": request_hash,
        "expected_source_stream_version": stream_version,
        **lease,
        "authority_revision": _required_text(values["authority_revision"], "authority_revision"),
        "workspace_revision": workspace,
        "task_profile_revision": _required_text(
            values["task_profile_revision"], "task_profile_revision"
        ),
        "effective_depth_limit": depth,
        "artifact_id": artifact_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "abort_code": abort_code,
    }


def parse_envelope(record: SnapshotRecord) -> dict[str, object]:
    values = _record_values(
        record,
        {
            "handoff_id", "source_session_id", "target_session_id", "artifact_id",
            "envelope_json", "checksum",
        },
    )
    try:
        raw = values["envelope_json"]
        payload = json.loads(raw) if isinstance(raw, str) else raw
        envelope = SessionHandoffEnvelope.model_validate(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise HandoffMigrationError("Handoff envelope is malformed") from error
    handoff_id = _uuid(values["handoff_id"], "handoff_id")
    source_session_id = _uuid(values["source_session_id"], "source_session_id")
    target_session_id = _uuid(values["target_session_id"], "target_session_id")
    artifact_id = _required_text(values["artifact_id"], "artifact_id")
    checksum = _digest(values["checksum"], "checksum")
    if (
        envelope.handoff_id != handoff_id
        or envelope.source_session_id != source_session_id
        or envelope.target_session_id != target_session_id
        or envelope.checksum != checksum
        or envelope.expected_checksum() != checksum
    ):
        raise HandoffMigrationError("Handoff envelope identity or checksum changed")
    return {
        "handoff_id": handoff_id,
        "source_session_id": source_session_id,
        "target_session_id": target_session_id,
        "artifact_id": artifact_id,
        "checksum": checksum,
        "envelope": envelope,
    }


def parse_dispatch(record: SnapshotRecord) -> dict[str, object]:
    values = _record_values(
        record,
        {
            "delivery_id", "child_session_id", "handoff_id", "status", "claimed_by",
            "claim_token", "claim_epoch", "claim_fencing_token", "claim_owner_instance_id",
            "claim_expires_at", "created_at",
        },
    )
    status = str(values["status"])
    if status == "acked":
        raise HandoffMigrationError(
            "acked dispatch lacks authoritative ACK timestamp in SQLite"
        )
    if status not in {"pending", "claimed"}:
        raise HandoffMigrationError("dispatch status is unsupported")
    delivery_id = _uuid(values["delivery_id"], "delivery_id")
    child_session_id = _uuid(values["child_session_id"], "child_session_id")
    handoff_id = _uuid(values["handoff_id"], "handoff_id")
    created_at = _timestamp(values["created_at"], "created_at")
    claim_fields = (
        values["claim_token"], values["claim_epoch"], values["claim_fencing_token"],
        values["claim_owner_instance_id"], values["claim_expires_at"], values["claimed_by"],
    )
    if status == "pending":
        if any(value is not None for value in claim_fields):
            raise HandoffMigrationError("pending dispatch has claim state")
        claim: tuple[str | None, UUID | None, int | None, str | None, datetime | None] = (
            None, None, None, None, None
        )
    else:
        token = _required_text(values["claim_token"], "claim_token")
        epoch = _uuid(values["claim_epoch"], "claim_epoch")
        fencing = _integer(values["claim_fencing_token"], "claim_fencing_token")
        owner = _required_text(values["claim_owner_instance_id"], "claim_owner_instance_id")
        claimed_by = _required_text(values["claimed_by"], "claimed_by")
        if claimed_by != owner or fencing < 1:
            raise HandoffMigrationError("claimed dispatch owner or fence changed")
        expires_at = _timestamp(values["claim_expires_at"], "claim_expires_at")
        if expires_at <= created_at:
            raise HandoffMigrationError("claimed dispatch expiry is not after creation")
        claim = (token, epoch, fencing, owner, expires_at)
    return {
        "delivery_id": delivery_id,
        "child_session_id": child_session_id,
        "handoff_id": handoff_id,
        "status": status,
        "claim_token": claim[0],
        "claim_epoch": claim[1],
        "claim_fencing_token": claim[2],
        "claim_owner_instance_id": claim[3],
        "claim_expires_at": claim[4],
        "created_at": created_at,
    }


def parse_lineage(record: SnapshotRecord) -> dict[str, object]:
    values = _record_values(
        record,
        {"session_id", "root_session_id", "parent_session_id", "inbound_handoff_id", "stage_index"},
    )
    try:
        lineage = SessionLineage(
            session_id=SessionId(_uuid(values["session_id"], "lineage session_id")),
            root_session_id=SessionId(_uuid(values["root_session_id"], "lineage root_session_id")),
            parent_session_id=(
                None
                if values["parent_session_id"] is None
                else SessionId(_uuid(values["parent_session_id"], "lineage parent_session_id"))
            ),
            inbound_handoff_id=(
                None
                if values["inbound_handoff_id"] is None
                else HandoffId(_uuid(values["inbound_handoff_id"], "lineage inbound_handoff_id"))
            ),
            stage_index=_integer(values["stage_index"], "lineage stage_index"),
        )
    except (TypeError, ValueError) as error:
        raise HandoffMigrationError("Session lineage row is malformed") from error
    return {
        "session_id": UUID(str(lineage.session_id)),
        "root_session_id": UUID(str(lineage.root_session_id)),
        "parent_session_id": (
            None if lineage.parent_session_id is None else UUID(str(lineage.parent_session_id))
        ),
        "inbound_handoff_id": (
            None if lineage.inbound_handoff_id is None else UUID(str(lineage.inbound_handoff_id))
        ),
        "stage_index": lineage.stage_index,
    }


def _record_values(record: SnapshotRecord, expected: set[str]) -> dict[str, object]:
    if set(record.columns) != expected or len(record.columns) != len(record.values):
        raise HandoffMigrationError(f"unexpected {record.table} column contract")
    return dict(zip(record.columns, record.values, strict=True))


def _workspace(value: object) -> WorkspaceBindingRevision:
    try:
        raw = json.loads(value) if isinstance(value, str) else value
        return WorkspaceBindingRevision.model_validate(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise HandoffMigrationError("Handoff workspace revision is malformed") from error


def _lease(values: Mapping[str, object]) -> dict[str, object]:
    raw = (
        values["source_lease_epoch"],
        values["source_lease_fencing_token"],
        values["source_lease_owner_instance_id"],
    )
    if all(value is None for value in raw):
        return {
            "source_lease_epoch": None,
            "source_lease_fencing_token": None,
            "source_lease_owner_instance_id": None,
        }
    if any(value is None for value in raw):
        raise HandoffMigrationError("Handoff source lease fence is incomplete")
    token = _integer(raw[1], "source_lease_fencing_token")
    if token < 1:
        raise HandoffMigrationError("Handoff source lease fence is invalid")
    return {
        "source_lease_epoch": _uuid(raw[0], "source_lease_epoch"),
        "source_lease_fencing_token": token,
        "source_lease_owner_instance_id": _required_text(
            raw[2], "source_lease_owner_instance_id"
        ),
    }


def _uuid(value: object, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise HandoffMigrationError(f"{field} must be a UUID") from error


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise HandoffMigrationError(f"{field} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise HandoffMigrationError(f"{field} must be timezone-aware")
    return parsed


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise HandoffMigrationError(f"{field} must be an integer")
    try:
        if isinstance(value, int | str):
            return int(value)
        raise TypeError
    except (TypeError, ValueError) as error:
        raise HandoffMigrationError(f"{field} must be an integer") from error


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffMigrationError(f"{field} must not be blank")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _digest(value: object, field: str) -> str:
    digest = _required_text(value, field)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise HandoffMigrationError(f"{field} must be a lowercase SHA-256 digest")
    return digest
