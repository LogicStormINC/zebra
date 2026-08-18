import json
from datetime import datetime
from sqlite3 import Row
from uuid import UUID

from agent_core.domain.events import EventActor, EventType, SessionEvent


class SessionEventIdempotencyConflictError(ValueError):
    """Raised when one idempotency key is reused for a different operation."""


def serialize_event_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True)


def ensure_idempotent_event_retry(
    existing: SessionEvent,
    requested: SessionEvent,
) -> SessionEvent:
    """Return the first Event only when the retry has the same business meaning.

    A retried request may receive a new Event ID, sequence and timestamp before
    storage resolves its idempotency key. Those transport-assigned values do not
    change the operation represented by the Event.
    """
    existing_fingerprint = (
        existing.session_id,
        existing.event_type,
        existing.payload,
        existing.actor,
        existing.causation_id,
        existing.correlation_id,
        existing.idempotency_key,
        existing.policy_version,
        existing.model_profile,
    )
    requested_fingerprint = (
        requested.session_id,
        requested.event_type,
        requested.payload,
        requested.actor,
        requested.causation_id,
        requested.correlation_id,
        requested.idempotency_key,
        requested.policy_version,
        requested.model_profile,
    )
    if existing_fingerprint != requested_fingerprint:
        raise SessionEventIdempotencyConflictError(
            "session event idempotency key was reused with different content"
        )
    return existing


def deserialize_event_row(row: Row) -> SessionEvent:
    return SessionEvent.model_validate(
        {
            "event_id": UUID(row["event_id"]),
            "session_id": UUID(row["session_id"]),
            "sequence": row["sequence"],
            "event_type": EventType(row["event_type"]),
            "payload": json.loads(row["payload"]),
            "actor": EventActor(row["actor"]),
            "created_at": datetime.fromisoformat(row["created_at"]),
            "causation_id": UUID(row["causation_id"]) if row["causation_id"] else None,
            "correlation_id": (UUID(row["correlation_id"]) if row["correlation_id"] else None),
            "idempotency_key": row["idempotency_key"],
            "policy_version": row["policy_version"],
            "model_profile": row["model_profile"],
        }
    )
