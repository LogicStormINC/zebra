from collections.abc import Mapping

from ag_ui.core import CustomEvent

from agent_integrations.ag_ui.contracts import AgUiProjectionError


def project_answer_committed(
    payload: Mapping[str, object], *, timestamp: int
) -> CustomEvent:
    answer = payload.get("assistant_message")
    if not isinstance(answer, str) or not answer.strip():
        raise AgUiProjectionError("answer_committed assistant_message must be text")
    model_call_id = payload.get("model_call_id")
    return CustomEvent(
        timestamp=timestamp,
        name="zebra.answer_committed",
        value={
            "assistant_message": answer,
            "model_call_id": model_call_id if isinstance(model_call_id, str) else None,
            "delivery_assessment": payload.get("delivery_assessment", {}),
        },
    )
