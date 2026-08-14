"""Strict frozen Task policy parsers (Wave 5)."""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.attempt_policy import TaskAttemptPolicy


@dataclass(frozen=True)
class TaskFrozenFacts:
    """The Stable Task's frozen attempt policy and call budgets, recovered
    from the ordered root TASK_PREPARED facts so a handoff child can neither
    erase nor expand them."""

    policy: TaskAttemptPolicy
    max_model_calls: int | None
    max_tool_calls: int | None


def _check_segment_against_facts(
    payload: dict[str, object],
    task_facts: TaskFrozenFacts,
) -> None:
    policy = task_facts.policy
    pairs: list[tuple[str, object]] = [
        ("max_attempts", policy.max_attempts),
        ("max_corrections_per_attempt", policy.max_corrections_per_attempt),
        ("execution_profile_id", policy.execution_profile_id),
        ("retryable_stop_reasons", policy.retryable_stop_reasons),
        ("max_model_calls", task_facts.max_model_calls),
        ("max_tool_calls", task_facts.max_tool_calls),
    ]
    for key, expected in pairs:
        if key not in payload:
            continue
        raw = payload[key]
        present: object
        if key == "retryable_stop_reasons":
            present = _strict_reasons(raw)
        elif key == "execution_profile_id":
            present = _strict_text(raw, key)
        else:
            present = _strict_optional(
                raw,
                key,
                positive=key != "max_corrections_per_attempt",
                non_negative=key == "max_corrections_per_attempt",
            )
        if present is None:
            continue
        if expected is None or present != expected:
            raise ValueError(f"queued session task policy drift detected: {key}")


def _merge_fact[T](
    established: T,
    present: object,
    field: str,
) -> T:
    if present is None:
        return established
    if established != present:
        raise ValueError(f"queued session task policy drift detected: {field}")
    return established


def _strict_optional(
    value: object,
    field: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"queued session {field} must be an integer")
    if positive and value <= 0:
        raise ValueError(f"queued session {field} must be positive")
    if non_negative and value < 0:
        raise ValueError(f"queued session {field} must be non-negative")
    return value


def _strict_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"queued session {field} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"queued session {field} must not be blank")
    return stripped


def _strict_reasons(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("queued session retryable_stop_reasons must be a list")
    reasons: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("queued session retryable_stop_reasons must be non-blank")
        if item.strip() not in reasons:
            reasons.append(item.strip())
    return tuple(reasons)
