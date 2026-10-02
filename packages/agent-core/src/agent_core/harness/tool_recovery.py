"""Conservative observations for expected gateway failures, shared by both batches."""

from collections.abc import Mapping
from datetime import datetime

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.attempt_result import action_fingerprint
from agent_core.harness.model_step_support import tool_result_message
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.tool_gateway import ToolGatewayPort


def execute_observed(tool_gateway: ToolGatewayPort, tool_call: ToolCall) -> ToolResult:
    # Catch external/input failures, not cancellation or runtime invariants.
    try:
        result = tool_gateway.execute(tool_call)
    except (ValueError, OSError) as exc:
        transient = isinstance(exc, TimeoutError | ConnectionError)
        missing = isinstance(exc, FileNotFoundError)
        denied = isinstance(exc, PermissionError)
        result = ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            output=(
                "The tool did not return a successful result. Inspect the tool schema or "
                "resource and choose an allowed alternative. Do not assume a write failed."
            ),
            metadata={
                "reason": "tool_gateway_error",
                "error_type": type(exc).__name__,
                "category": "permission"
                if denied
                else "resource"
                if missing
                else "network"
                if transient
                else "input_or_execution",
                "retryable": transient,
                # Exception text can contain credentials/headers; adapters may provide
                # their own sanitized detail through a structured ToolResult instead.
                "execution_state": "unknown",
            },
        )
    return normalize_failure(
        result, read_only=tool_call.name in getattr(tool_gateway, "read_only_tools", ())
    )


def normalize_failure(result: ToolResult, *, read_only: bool) -> ToolResult:
    if result.status is not ToolCallStatus.FAILED:
        return result
    metadata = dict(result.metadata)
    state = metadata.get("execution_state")
    if state not in {"not_executed", "executed", "unknown"}:
        state = "not_executed" if metadata.get("executed") is False else "unknown"
    retryable = metadata.get("retryable") is True and read_only
    hint = (
        "Transient read failure: a bounded retry is allowed; respect retry_after_seconds. "
        "If it persists, use an allowed alternative."
        if retryable
        else "Do not repeat this write: its outcome is unknown. Read the resulting state or "
        "query its durable receipt before deciding what remains to do."
        if not read_only and state == "unknown"
        else "Correct the arguments using the tool schema, choose an allowed alternative, "
        "or report the missing outcome. Do not repeat identical failed calls or bypass policy."
    )
    return result.model_copy(
        update={
            "metadata": {
                **metadata,
                "code": metadata.get("code", metadata.get("reason", "tool_failed")),
                "category": metadata.get("category", "tool"),
                "execution_state": state,
                "retryable": retryable,
                "recovery_hint": hint,
            }
        }
    )


def record_recovery(
    metadata: dict[str, object],
    tool_call: ToolCall,
    result: ToolResult,
) -> dict[str, object]:
    attempts = _entries(metadata)
    fingerprint = action_fingerprint(tool_call)
    previous = attempts.get(fingerprint, {})
    count = previous.get("failures", 0)
    count = count if isinstance(count, int) and not isinstance(count, bool) else 0
    attempts[fingerprint] = {
        "failures": count + (result.status is ToolCallStatus.FAILED),
        "retryable": result.status is ToolCallStatus.FAILED
        and result.metadata.get("retryable") is True,
        "retry_after_seconds": result.metadata.get("retry_after_seconds", 0),
    }
    return {**metadata, "tool_recovery": attempts}


def can_retry_read(tool_call: ToolCall, metadata: Mapping[str, object]) -> bool:
    previous = _entries(metadata).get(action_fingerprint(tool_call), {})
    count = previous.get("failures")
    # ponytail: delayed retries belong to transport/scheduler, never sleep inside
    # deterministic Harness. A Retry-After result is not immediately reissued.
    delay = previous.get("retry_after_seconds", 0)
    return (
        previous.get("retryable") is True
        and isinstance(count, int)
        and 0 < count < 3
        and isinstance(delay, int | float)
        and delay <= 0
    )


def invalid_request_count(metadata: Mapping[str, object]) -> int:
    value = metadata.get("invalid_tool_requests", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _entries(metadata: Mapping[str, object]) -> dict[str, dict[str, object]]:
    raw = metadata.get("tool_recovery")
    return (
        {
            key: dict(value)
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        if isinstance(raw, dict)
        else {}
    )


def reject_tool_batch(
    calls: tuple[ToolCall, ...],
    *,
    reason: str,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
    created_at: datetime,
    attempt_number: int,
) -> None:
    """Pair every unexecuted call so the model can correct a malformed batch."""
    for call in calls:
        result = normalize_failure(
            ToolResult(
                tool_call_id=call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output=reason,
                metadata={
                    "reason": "invalid_tool_request",
                    "category": "input",
                    "executed": False,
                    "retryable": False,
                },
            ),
            read_only=True,
        )
        messages.append(tool_result_message(call, result, created_at=created_at))
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_FAILED,
                actor=EventActor.TOOL,
                payload={
                    "attempt_number": attempt_number,
                    "tool_name": call.name,
                    "tool_call_id": str(call.tool_call_id),
                    "status": result.status.value,
                    "output": result.output,
                    "metadata": result.metadata,
                },
            )
        )
