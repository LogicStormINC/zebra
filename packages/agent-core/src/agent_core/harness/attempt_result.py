import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessEventDraft,
)


def build_attempt_result(
    *,
    outcome: HarnessAttemptOutcome,
    summary: str,
    assistant_message: str,
    model_calls_used: int,
    tool_calls_executed: int,
    emitted_events: list[HarnessEventDraft],
    metadata: dict[str, object],
) -> HarnessAttemptResult:
    return HarnessAttemptResult(
        outcome=outcome,
        summary=summary,
        metadata={
            "assistant_message": assistant_message,
            "model_calls_used": model_calls_used,
            "tool_calls_executed": tool_calls_executed,
            **metadata,
        },
        emitted_events=tuple(emitted_events),
    )


def action_fingerprint(tool_call: ToolCall) -> str:
    return json.dumps(
        {"name": tool_call.name, "arguments": tool_call.arguments},
        separators=(",", ":"),
        sort_keys=True,
    )


def observation_fingerprint(tool_call: ToolCall, tool_result: ToolResult) -> str | None:
    if tool_result.metadata.get("reason") == "repeated_tool_call":
        return None
    payload = {
        "tool_name": tool_call.name,
        "status": tool_result.status.value,
        "summary": _normalized_result_summary(tool_result),
        "references": _stable_references(tool_result.metadata),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha256(encoded).hexdigest()


def update_observation_progress(
    metadata: Mapping[str, object],
    observations: Iterable[tuple[ToolCall, ToolResult]],
    *,
    state_changed: bool,
    threshold: int,
) -> dict[str, object]:
    if threshold <= 0:
        raise ValueError("observation progress threshold must be positive")
    seen = _string_set(metadata.get("observation_fingerprints"))
    batch = {
        fingerprint
        for tool_call, tool_result in observations
        if (fingerprint := observation_fingerprint(tool_call, tool_result)) is not None
    }
    new_evidence = bool(batch - seen)
    prior_count = metadata.get("consecutive_no_progress_batches", 0)
    count = (
        0
        if new_evidence or state_changed
        else prior_count + 1
        if isinstance(prior_count, int) and not isinstance(prior_count, bool)
        else 1
    )
    return {
        **metadata,
        "observation_fingerprints": sorted(seen | batch),
        "consecutive_no_progress_batches": count,
        "tool_loop_no_progress": count >= threshold,
    }


def update_batch_observation_progress(
    metadata: Mapping[str, object],
    observations: Iterable[tuple[ToolCall, ToolResult]],
    events: Iterable[HarnessEventDraft],
    *,
    threshold: int,
) -> dict[str, object]:
    return update_observation_progress(
        metadata,
        observations,
        state_changed=any(
            event.event_type in {EventType.PLAN_UPDATED, EventType.APPROVAL_REQUESTED}
            for event in events
        ),
        threshold=threshold,
    )


def append_no_progress_observation(
    messages: list[SessionMessage],
    *,
    metadata: Mapping[str, object],
    created_at: datetime,
) -> None:
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content="Runtime convergence observation: "
            + json.dumps(
                {
                    "type": "tool_loop_no_progress",
                    "consecutive_no_progress_batches": metadata.get(
                        "consecutive_no_progress_batches", 0
                    ),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\nUse the available tool results to answer the original request. "
            "Do not request or invoke another tool.",
            created_at=created_at,
            metadata={"tool_loop_no_progress": True},
        )
    )


def _normalized_result_summary(tool_result: ToolResult) -> str:
    output_checksum = tool_result.metadata.get("output_sha256")
    if isinstance(output_checksum, str) and output_checksum.strip():
        return f"sha256:{output_checksum.strip()}"
    if tool_result.output:
        try:
            return json.dumps(
                json.loads(tool_result.output),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except json.JSONDecodeError:
            return " ".join(tool_result.output.split())
    summary: dict[str, Any] = {"status": tool_result.status.value}
    for key in ("reason", "detail"):
        value = tool_result.metadata.get(key)
        if isinstance(value, str | int | float | bool):
            summary[key] = value
    return json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _stable_references(metadata: Mapping[str, object]) -> list[str]:
    keys = {
        "artifact_ref",
        "artifact_id",
        "source_uri",
        "source_url",
        "source_id",
        "resource_uri",
        "resource_id",
        "citation",
        "citations",
    }
    references: set[str] = set()
    for key, value in metadata.items():
        if key not in keys:
            continue
        if isinstance(value, str) and value.strip():
            references.add(value.strip())
        elif isinstance(value, list | tuple):
            references.update(
                item.strip() for item in value if isinstance(item, str) and item.strip()
            )
    return sorted(references)


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list | tuple | set):
        return set()
    return {item for item in value if isinstance(item, str)}
