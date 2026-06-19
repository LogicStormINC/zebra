import json
from datetime import datetime
from sqlite3 import Row
from uuid import UUID

from agent_core.domain.events import EventActor, EventType, SessionEvent


def serialize_event_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True)


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
            "correlation_id": (
                UUID(row["correlation_id"]) if row["correlation_id"] else None
            ),
            "idempotency_key": row["idempotency_key"],
            "policy_version": row["policy_version"],
            "model_profile": row["model_profile"],
        }
    )
