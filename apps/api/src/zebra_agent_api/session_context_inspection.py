import json

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.modeling import ModelContextWindow


def estimate_tokens(value: object) -> int:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return max(1, (len(encoded) + 3) // 4)


def context_occupancy(
    events: list[SessionEvent],
    latest: SessionEvent | None,
) -> dict[str, object]:
    groups = {"stable_prefix": 0, "messages": 0, "tools": 0, "capsule": 0}
    artifact_refs: set[str] = set()
    for event in events:
        tokens = estimate_tokens(event.payload)
        if event.event_type in {EventType.SESSION_CREATED, EventType.TASK_PREPARED}:
            groups["stable_prefix"] += tokens
        elif event.event_type in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
            EventType.TESTS_COMPLETED,
        }:
            groups["tools"] += tokens
        elif event.event_type is not EventType.CONTEXT_COMPACTED:
            groups["messages"] += tokens
        metadata = event.payload.get("metadata")
        if isinstance(metadata, dict):
            uri = metadata.get("artifact_uri")
            if isinstance(uri, str):
                artifact_refs.add(uri)
    if latest is not None and isinstance(latest.payload.get("capsule"), dict):
        groups["capsule"] = estimate_tokens(latest.payload["capsule"])
    latest_request = next(
        (
            event
            for event in reversed(events)
            if event.event_type is EventType.MODEL_REQUEST_STARTED
        ),
        None,
    )
    default_window = ModelContextWindow()
    limit = (
        latest_request.payload.get("input_token_limit")
        if latest_request is not None
        else default_window.input_token_limit
    )
    reserves = latest_request.payload.get("reserves") if latest_request else None
    return {
        "estimated_tokens": sum(groups.values()),
        "categories": groups,
        "hard_input_limit": limit,
        "reserves": reserves
        if isinstance(reserves, dict)
        else {
            "output": default_window.max_output_tokens,
            "reasoning": default_window.reasoning_reserve_tokens,
            "compaction": default_window.compaction_reserve_tokens,
            "protocol_and_emergency": default_window.protocol_reserve_tokens,
        },
        "retained_event_count": len(events),
        "artifact_reference_count": len(artifact_refs),
    }
