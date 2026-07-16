from __future__ import annotations

from zebra_agent_cli.session_memory_ranking import (
    _action_priority_rank,
    _overdue_retention_breach_action_rank,
    _overdue_retention_breach_age_bucket_rank,
    _overdue_retention_breach_lane_rank,
    _overdue_retention_breach_owner_target_rank,
)


def _highest_priority_overdue_retention_guidance_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        guidance = scope.get("overdue_retention_guidance")
        priority = scope.get("overdue_retention_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_target_memory_id")
        bucket = scope.get("overdue_retention_bucket")
        reasons = scope.get("overdue_retention_reasons")
        if not (
            overdue is True
            and isinstance(guidance, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(bucket, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_guidance": guidance,
            "overdue_retention_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_bucket": bucket,
            "overdue_retention_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_window_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        window = scope.get("overdue_retention_window")
        priority = scope.get("overdue_retention_window_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("overdue_retention_window_due_at")
        target_memory_id = scope.get("overdue_retention_window_target_memory_id")
        reasons = scope.get("overdue_retention_window_reasons")
        if not (
            overdue is True
            and isinstance(window, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_window": window,
            "overdue_retention_window_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_window_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_window_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        breach = scope.get("overdue_retention_breach")
        priority = scope.get("overdue_retention_breach_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("overdue_retention_breach_due_at")
        target_memory_id = scope.get("overdue_retention_breach_target_memory_id")
        reasons = scope.get("overdue_retention_breach_reasons")
        if not (
            overdue is True
            and isinstance(breach, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach": breach,
            "overdue_retention_breach_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_breach_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_aging_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        bucket = scope.get("overdue_retention_breach_age_bucket")
        age_seconds = scope.get("overdue_retention_breach_age_seconds")
        age_days = scope.get("overdue_retention_breach_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        reasons = scope.get("overdue_retention_breach_age_reasons")
        if not (
            isinstance(bucket, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_age_bucket": bucket,
            "overdue_retention_breach_age_seconds": age_seconds,
            "overdue_retention_breach_age_days": age_days,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "overdue_retention_breach_age_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_age_bucket_rank(
            bucket
        ) > _overdue_retention_breach_age_bucket_rank(
            str(highest["overdue_retention_breach_age_bucket"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_action_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        action = scope.get("overdue_retention_breach_action")
        priority = scope.get("overdue_retention_breach_action_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_action_target_memory_id")
        reasons = scope.get("overdue_retention_breach_action_reasons")
        if not (
            isinstance(action, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_action": action,
            "overdue_retention_breach_action_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_action_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_action_rank(
            action
        ) > _overdue_retention_breach_action_rank(str(highest["overdue_retention_breach_action"])):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_lane_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        lane = scope.get("overdue_retention_breach_lane")
        priority = scope.get("overdue_retention_breach_lane_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_lane_target_memory_id")
        reasons = scope.get("overdue_retention_breach_lane_reasons")
        if not (
            isinstance(lane, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_lane": lane,
            "overdue_retention_breach_lane_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_lane_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_lane_rank(
            lane
        ) > _overdue_retention_breach_lane_rank(str(highest["overdue_retention_breach_lane"])):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_owner_target_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        owner_target = scope.get("overdue_retention_breach_owner_target")
        priority = scope.get("overdue_retention_breach_owner_target_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_owner_target_memory_id")
        reasons = scope.get("overdue_retention_breach_owner_target_reasons")
        if not (
            isinstance(owner_target, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_owner_target": owner_target,
            "overdue_retention_breach_owner_target_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_owner_target_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_owner_target_rank(
            owner_target
        ) > _overdue_retention_breach_owner_target_rank(
            str(highest["overdue_retention_breach_owner_target"])
        ):
            highest = candidate
    return highest
