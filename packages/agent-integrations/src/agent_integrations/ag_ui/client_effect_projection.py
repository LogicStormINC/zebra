"""Pure AG-UI state projection for durable browser effects."""

from ag_ui.core import Event, StateDeltaEvent
from agent_core.domain.events import EventType, SessionEvent


def project_client_effect(event: SessionEvent, *, timestamp: int) -> tuple[Event, ...] | None:
    """Project scheduled/terminal events under ``/zebra/clientEffects``."""

    payload = event.payload
    effect_id = payload.get("client_effect_id")
    if not isinstance(effect_id, str) or not effect_id:
        return None
    path = f"/zebra/clientEffects/{effect_id}"
    if event.event_type is EventType.CLIENT_EFFECT_SCHEDULED:
        return (
            StateDeltaEvent(
                timestamp=timestamp,
                delta=[
                    {
                        "op": "add",
                        "path": path,
                        "value": {
                            "effect_id": effect_id,
                            "action_name": payload.get("action_name"),
                            "arguments": payload.get("arguments", {}),
                            "action_contract_digest": payload.get("action_contract_digest"),
                            "client_binding_digest": payload.get("client_binding_digest"),
                            "expected_ui_revision": payload.get("expected_ui_revision"),
                            "request_digest": payload.get("request_digest"),
                            "execution_location": "client",
                            "status": "pending",
                        },
                    }
                ],
            ),
        )
    if event.event_type is EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED:
        return (
            StateDeltaEvent(
                timestamp=timestamp,
                delta=[{"op": "remove", "path": path}],
            ),
        )
    return None
