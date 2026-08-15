from collections.abc import Mapping
from dataclasses import replace

from agent_core.domain.events import EventType
from agent_core.domain.modeling import (
    ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME,
    ModelCompletion,
)
from agent_core.harness.models import HarnessEventDraft


def final_output_contract(
    emitted_events: list[HarnessEventDraft],
    completion: ModelCompletion,
) -> dict[str, object] | None:
    """Return the last legal emit-tool contract, else the model contract."""
    emitted: dict[str, object] | None = None
    for event in emitted_events:
        if (
            event.event_type is EventType.TOOL_EXECUTION_COMPLETED
            and event.payload.get("tool_name")
            == ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME
        ):
            metadata = event.payload.get("metadata")
            candidate = (
                metadata.get("output_contract")
                if isinstance(metadata, Mapping)
                else None
            )
            if isinstance(candidate, Mapping):
                emitted = dict(candidate)
    if emitted is not None:
        return emitted
    return (
        dict(completion.output_contract)
        if completion.output_contract is not None
        else None
    )


def bind_final_output_contract(
    emitted_events: list[HarnessEventDraft],
    contract: dict[str, object] | None,
) -> None:
    if contract is None:
        return
    for index in range(len(emitted_events) - 1, -1, -1):
        event = emitted_events[index]
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            emitted_events[index] = replace(
                event,
                payload={**event.payload, "output_contract": dict(contract)},
            )
            return
