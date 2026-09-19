"""Pure projection for the field-owned Client State namespace."""

import json
from hashlib import sha256

from ag_ui.core import Event, StateDeltaEvent
from agent_core.domain.events import EventType, SessionEvent


def project_client_state(event: SessionEvent, *, timestamp: int) -> tuple[Event, ...] | None:
    if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
        return None
    command = event.payload.get("payload")
    client = command.get("client") if isinstance(command, dict) else None
    if not isinstance(client, dict):
        return None
    state = client.get("state_snapshot")
    if not isinstance(state, dict) or not state:
        return None
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    digest = sha256(encoded).hexdigest()
    if client.get("state_digest") != digest:
        return None
    return (
        StateDeltaEvent(
            timestamp=timestamp,
            delta=[
                {
                    "op": "add",
                    "path": "/client",
                    "value": {
                        "owner": "host_frontend",
                        "frontend_app_id": client.get("frontend_app_id"),
                        "profile_digest": client.get("profile_digest"),
                        "ui_revision": client.get("ui_revision"),
                        "state_digest": digest,
                        "readables": state,
                    },
                }
            ],
        ),
    )
