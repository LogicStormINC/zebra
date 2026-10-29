"""Revision-two state; revision-one snapshot bytes and storage kinds stay frozen."""

import json
from dataclasses import dataclass, field, fields

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.standard_state import (
    MAX_STANDARD_STATE_BYTES,
    StandardProjectionState,
)


@dataclass(slots=True)
class InteractionProjectionState(StandardProjectionState):
    interrupt_ack_pending: bool = False
    accepted_receipt: dict[str, str] = field(default_factory=dict)
    pending_clarification: dict[str, str] = field(default_factory=dict)
    pending_effects: dict[str, dict[str, object]] = field(default_factory=dict)

    def snapshot(self) -> str:
        data = json.loads(StandardProjectionState.snapshot(self))
        data.update(
            version=2,
            pending_effects=self.pending_effects,
            interrupt_ack_pending=self.interrupt_ack_pending,
            accepted_receipt=self.accepted_receipt,
            pending_clarification=self.pending_clarification,
        )
        value = json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        if len(value.encode()) > MAX_STANDARD_STATE_BYTES:
            raise AgUiProjectionError("interaction checkpoint exceeds state bound")
        return value

    @classmethod
    def restore(cls, value: str) -> "InteractionProjectionState":
        try:
            if len(value.encode()) > MAX_STANDARD_STATE_BYTES:
                raise ValueError("state budget")
            data = json.loads(value)
            if data.pop("version") != 2:
                raise ValueError("revision mismatch")
            clarification = data.pop("pending_clarification")
            if (
                not isinstance(clarification, dict)
                or clarification
                and (
                    set(clarification)
                    != {"operation_id", "clarification_id", "content_hash", "source_event_id"}
                    or any(not isinstance(v, str) or not v for v in clarification.values())
                )
            ):
                raise ValueError("invalid human receipt state")
            accepted = data.pop("accepted_receipt")
            if (
                not isinstance(accepted, dict)
                or accepted
                and (
                    set(accepted)
                    != {
                        "effect_id",
                        "tool_call_id",
                        "action_name",
                        "request_digest",
                        "status",
                        "receipt_id",
                        "event_id",
                        "sequence",
                    }
                    or any(not isinstance(v, str) or not v for v in accepted.values())
                )
            ):
                raise ValueError("invalid accepted receipt state")
            acknowledgement = data.pop("interrupt_ack_pending")
            if type(acknowledgement) is not bool:
                raise ValueError("invalid native acknowledgement state")
            effects = data.pop("pending_effects")
            if not isinstance(effects, dict) or len(effects) > 1:
                raise ValueError("unsupported native effect combination")
            if any(
                not isinstance(key, str)
                or not isinstance(effect, dict)
                or effect.get("effect_id") != key
                or effect.get("execution_location") != "client"
                or effect.get("status") != "pending"
                for key, effect in effects.items()
            ):
                raise ValueError("invalid effect state")
            execution = data["public_execution"]
            waiting = execution.get("status") == "waiting_client_effect"
            if waiting:
                data["public_execution"] = {**execution, "status": "paused"}
            data["version"] = 1
            base = StandardProjectionState.restore(json.dumps(data))
            result = cls(
                **{f.name: getattr(base, f.name) for f in fields(base)},
                pending_effects=effects,
                interrupt_ack_pending=acknowledgement,
                accepted_receipt=accepted,
                pending_clarification=clarification,
            )
            if waiting:
                result.public_execution = execution
            return result
        except (ValueError, TypeError, KeyError, RecursionError):
            raise AgUiProjectionError("invalid interaction checkpoint state") from None

    def begin(self, run_id: str, anchor: str) -> None:
        StandardProjectionState.begin(self, run_id, anchor)
        self.interrupt_ack_pending = False
        self.open_interrupts.clear()
        self.checkpoint_interrupt_ids.clear()
