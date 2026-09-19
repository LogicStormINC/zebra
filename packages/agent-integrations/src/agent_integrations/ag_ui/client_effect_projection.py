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
        required = {
            key: payload.get(key)
            for key in (
                "task_id",
                "run_id",
                "surface_instance_id",
                "action_name",
                "action_contract_digest",
                "client_binding_digest",
                "request_digest",
                "idempotency_key",
                "expires_at",
            )
        }
        if any(not isinstance(value, str) or not value for value in required.values()):
            # Historical sparse schedule events remain readable but are never executable.
            return None
        arguments = payload.get("arguments", {})
        expected_revision = payload.get("expected_ui_revision")
        if not isinstance(arguments, dict) or not isinstance(expected_revision, int):
            return None
        return (
            StateDeltaEvent(
                timestamp=timestamp,
                delta=[
                    {
                        "op": "add",
                        "path": path,
                        "value": {
                            "effect_id": effect_id,
                            "task_id": required["task_id"],
                            "run_id": required["run_id"],
                            "surface_instance_id": required["surface_instance_id"],
                            "action_name": required["action_name"],
                            "arguments": arguments,
                            "action_contract_digest": required["action_contract_digest"],
                            "capability_version": required["action_contract_digest"],
                            "client_binding_digest": required["client_binding_digest"],
                            "expected_ui_revision": expected_revision,
                            "deadline": required["expires_at"],
                            "expires_at": required["expires_at"],
                            "idempotency_key": required["idempotency_key"],
                            "request_digest": required["request_digest"],
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
