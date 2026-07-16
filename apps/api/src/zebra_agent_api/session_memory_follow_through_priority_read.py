from __future__ import annotations

from zebra_agent_api.session_memory_ranking import (
    _overdue_retention_breach_follow_through_completion_rank,
    _overdue_retention_breach_follow_through_outcome_rank,
    _overdue_retention_breach_follow_through_rank,
    _overdue_retention_breach_follow_through_verification_outcome_rank,
    _overdue_retention_breach_follow_through_verification_rank,
)


def _highest_priority_overdue_retention_breach_follow_through_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        mode = scope.get("overdue_retention_breach_follow_through_mode")
        priority = scope.get("overdue_retention_breach_follow_through_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_follow_through_memory_id")
        reasons = scope.get("overdue_retention_breach_follow_through_reasons")
        if not (
            isinstance(mode, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_mode": mode,
            "overdue_retention_breach_follow_through_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_follow_through_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_rank(
            mode
        ) > _overdue_retention_breach_follow_through_rank(
            str(highest["overdue_retention_breach_follow_through_mode"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_outcome")
        priority = scope.get("overdue_retention_breach_follow_through_outcome_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_follow_through_outcome_memory_id")
        reasons = scope.get("overdue_retention_breach_follow_through_outcome_reasons")
        if not (
            isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_outcome": outcome,
            "overdue_retention_breach_follow_through_outcome_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_follow_through_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_outcome_rank(
            outcome
        ) > _overdue_retention_breach_follow_through_outcome_rank(
            str(highest["overdue_retention_breach_follow_through_outcome"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_completion_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_completion_state")
        priority = scope.get("overdue_retention_breach_follow_through_completion_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_follow_through_completion_memory_id")
        reasons = scope.get("overdue_retention_breach_follow_through_completion_reasons")
        if not (
            isinstance(state, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_completion_state": state,
            "overdue_retention_breach_follow_through_completion_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_follow_through_completion_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_completion_rank(
            state
        ) > _overdue_retention_breach_follow_through_completion_rank(
            str(highest["overdue_retention_breach_follow_through_completion_state"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_verification_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_verification_state")
        priority = scope.get("overdue_retention_breach_follow_through_verification_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_verification_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_verification_reasons")
        if not (
            isinstance(state, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_verification_state": state,
            "overdue_retention_breach_follow_through_verification_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_follow_through_verification_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_verification_rank(
            state
        ) > _overdue_retention_breach_follow_through_verification_rank(
            str(highest["overdue_retention_breach_follow_through_verification_state"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_verification_outcome")
        priority = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_priority"
        )
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_verification_outcome_reasons")
        if not (
            isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_verification_outcome": outcome,
            "overdue_retention_breach_follow_through_verification_outcome_priority": (priority),
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_retention_breach_follow_through_verification_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_verification_outcome_rank(
            outcome
        ) > _overdue_retention_breach_follow_through_verification_outcome_rank(
            str(highest["overdue_retention_breach_follow_through_verification_outcome"])
        ):
            highest = candidate
    return highest
