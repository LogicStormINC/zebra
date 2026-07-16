from __future__ import annotations

from typing import cast

from zebra_agent_api.session_memory_ranking import (
    _action_priority_rank,
    _overdue_age_bucket_rank,
)


def _highest_priority_action_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        hint = scope.get("action_hint")
        priority = scope.get("action_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("action_target_memory_id")
        reasons = scope.get("action_reasons")
        if not (
            isinstance(hint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "action_hint": hint,
            "action_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "action_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["action_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_escalation_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        recommendation = scope.get("escalation_recommendation")
        priority = scope.get("escalation_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("escalation_target_memory_id")
        reasons = scope.get("escalation_reasons")
        if not (
            isinstance(recommendation, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "escalation_recommendation": recommendation,
            "escalation_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "escalation_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["escalation_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_follow_up_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        window = scope.get("follow_up_window")
        priority = scope.get("follow_up_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("follow_up_due_at")
        target_memory_id = scope.get("follow_up_target_memory_id")
        reasons = scope.get("follow_up_reasons")
        if not (
            isinstance(window, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "follow_up_window": window,
            "follow_up_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "follow_up_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["follow_up_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        priority = scope.get("follow_up_overdue_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        overdue_since = scope.get("follow_up_overdue_since")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("follow_up_overdue_reasons")
        if not (
            overdue is True
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(overdue_since, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "follow_up_overdue_priority": priority,
            "follow_up_overdue_since": overdue_since,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "follow_up_overdue_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["follow_up_overdue_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_age_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        bucket = scope.get("overdue_age_bucket")
        age_seconds = scope.get("overdue_age_seconds")
        age_days = scope.get("overdue_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("overdue_age_reasons")
        if not (
            overdue is True
            and isinstance(bucket, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_age_bucket": bucket,
            "overdue_age_seconds": age_seconds,
            "overdue_age_days": age_days,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_age_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _overdue_age_bucket_rank(bucket) > _overdue_age_bucket_rank(
            str(highest["overdue_age_bucket"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_type_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        memory_type = scope.get("highest_overdue_memory_type")
        count = scope.get("highest_overdue_memory_type_count")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        target_memory_type = scope.get("overdue_target_memory_type")
        reasons = scope.get("overdue_type_rollup_reasons")
        if not (
            overdue is True
            and isinstance(memory_type, str)
            and isinstance(count, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "highest_overdue_memory_type": memory_type,
            "highest_overdue_memory_type_count": count,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_target_memory_type": (
                target_memory_type if isinstance(target_memory_type, str) else None
            ),
            "overdue_type_rollup_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_count = cast(int, highest["highest_overdue_memory_type_count"])
        highest_type = highest["highest_overdue_memory_type"]
        if count > highest_count or (count == highest_count and memory_type < str(highest_type)):
            highest = candidate
    return highest


def _highest_priority_overdue_visibility_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        visibility = scope.get("highest_overdue_memory_visibility")
        count = scope.get("highest_overdue_memory_visibility_count")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        target_memory_visibility = scope.get("overdue_target_memory_visibility")
        reasons = scope.get("overdue_visibility_rollup_reasons")
        if not (
            overdue is True
            and isinstance(visibility, str)
            and isinstance(count, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "highest_overdue_memory_visibility": visibility,
            "highest_overdue_memory_visibility_count": count,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_target_memory_visibility": (
                target_memory_visibility if isinstance(target_memory_visibility, str) else None
            ),
            "overdue_visibility_rollup_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_count = cast(int, highest["highest_overdue_memory_visibility_count"])
        highest_visibility = highest["highest_overdue_memory_visibility"]
        if count > highest_count or (
            count == highest_count and visibility < str(highest_visibility)
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_trend_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        signal = scope.get("overdue_trend_signal")
        rank = scope.get("overdue_trend_rank")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("overdue_trend_reasons")
        if not (
            overdue is True
            and isinstance(signal, str)
            and isinstance(rank, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_trend_signal": signal,
            "overdue_trend_rank": rank,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_trend_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None:
            highest = candidate
            continue
        highest_rank = cast(int, highest["overdue_trend_rank"])
        highest_signal = highest["overdue_trend_signal"]
        if rank > highest_rank or (rank == highest_rank and signal < str(highest_signal)):
            highest = candidate
    return highest


def _highest_priority_overdue_intervention_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        hint = scope.get("overdue_intervention_hint")
        priority = scope.get("overdue_intervention_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_intervention_target_memory_id")
        reasons = scope.get("overdue_intervention_reasons")
        if not (
            overdue is True
            and isinstance(hint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_intervention_hint": hint,
            "overdue_intervention_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_intervention_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_intervention_priority"])
        ):
            highest = candidate
    return highest
