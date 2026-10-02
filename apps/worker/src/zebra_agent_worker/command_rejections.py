"""Permanent legacy validation outcomes in the existing idempotency receipt store."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from agent_core.domain.events import SessionEvent
from agent_core.ports.idempotency_store import IdempotencyRecord, IdempotencyStorePort
from agent_storage.postgres.legacy_command_candidates import LEGACY_REJECTION_ACTION


def command_rejected(store: IdempotencyStorePort, event: SessionEvent) -> bool:
    receipt = store.get(action=LEGACY_REJECTION_ACTION, idempotency_key=str(event.event_id))
    if receipt is None:
        return False
    if receipt.request_hash != _fingerprint(event):
        raise ValueError("legacy rejection receipt conflicts with canonical command")
    return True


def reject_command(
    store: IdempotencyStorePort,
    event: SessionEvent,
    reason: Literal["invalid_command", "unsupported_control"],
) -> None:
    store.save(IdempotencyRecord(
        action=LEGACY_REJECTION_ACTION,
        idempotency_key=str(event.event_id),
        request_hash=_fingerprint(event),
        status_code=422 if reason == "invalid_command" else 501,
        response_body={
            "status": "rejected", "reason": reason,
            "accepted_event_id": str(event.event_id), "session_id": str(event.session_id),
        },
        created_at=datetime.now(UTC),
    ))


def _fingerprint(event: SessionEvent) -> str:
    return sha256(event.model_dump_json().encode()).hexdigest()
