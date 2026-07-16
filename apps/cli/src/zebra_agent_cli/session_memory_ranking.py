from __future__ import annotations

from datetime import UTC, datetime


def _oldest_pending_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    oldest: dict[str, object] | None = None
    for scope in scopes:
        captured_at = scope.get("oldest_pending_captured_at")
        memory_id = scope.get("oldest_pending_memory_id")
        age_seconds = scope.get("oldest_pending_age_seconds")
        age_days = scope.get("oldest_pending_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        if not (
            isinstance(captured_at, str)
            and isinstance(memory_id, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
        ):
            continue
        candidate = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "memory_id": memory_id,
            "captured_at": captured_at,
            "age_seconds": age_seconds,
            "age_days": age_days,
        }
        if oldest is None or captured_at < str(oldest["captured_at"]):
            oldest = candidate
    return oldest


def _pressure_rank(level: str) -> int:
    ranks = {
        "clear": 0,
        "steady": 1,
        "elevated": 2,
        "high": 3,
    }
    return ranks.get(level, -1)


def _overdue_age_bucket_rank(bucket: str) -> int:
    ranks = {
        "not_overdue": 0,
        "unknown_overdue_age": 0,
        "lt_1d_overdue": 1,
        "gte_1d_lt_3d_overdue": 2,
        "gte_3d_lt_7d_overdue": 3,
        "gte_7d_overdue": 4,
    }
    return ranks.get(bucket, -1)


def _overdue_retention_breach_age_bucket_rank(bucket: str) -> int:
    ranks = {
        "not_breached": 0,
        "unknown_breach_age": 0,
        "lt_1d_breached": 1,
        "gte_1d_lt_3d_breached": 2,
        "gte_3d_lt_7d_breached": 3,
        "gte_7d_breached": 4,
    }
    return ranks.get(bucket, -1)


def _overdue_retention_breach_action_rank(action: str) -> int:
    ranks = {
        "no_retention_action": 0,
        "inspect_breach_timestamps": 1,
        "queue_immediate_retention_review": 2,
        "assign_retention_owner": 3,
        "escalate_retention_decision": 4,
        "force_archive_or_override": 5,
    }
    return ranks.get(action, -1)


def _overdue_retention_breach_lane_rank(lane: str) -> int:
    ranks = {
        "no_retention_lane": 0,
        "operator_timestamp_review_lane": 1,
        "operator_retention_review_lane": 2,
        "owner_assignment_lane": 3,
        "manager_retention_escalation_lane": 4,
        "emergency_retention_override_lane": 5,
    }
    return ranks.get(lane, -1)


def _overdue_retention_breach_owner_target_rank(owner_target: str) -> int:
    ranks = {
        "no_owner_assignment": 0,
        "memory_operator": 1,
        "scope_owner": 2,
        "retention_manager": 3,
        "retention_admin": 4,
    }
    return ranks.get(owner_target, -1)


def _overdue_retention_breach_follow_through_rank(mode: str) -> int:
    ranks = {
        "no_follow_through_needed": 0,
        "operator_review_follow_through": 1,
        "owner_confirmation_follow_through": 2,
        "manager_decision_follow_through": 3,
        "admin_override_follow_through": 4,
    }
    return ranks.get(mode, -1)


def _overdue_retention_breach_follow_through_outcome_rank(outcome: str) -> int:
    ranks = {
        "no_follow_through_outstanding": 0,
        "follow_through_monitoring_only": 1,
        "awaiting_operator_follow_through": 2,
        "awaiting_owner_follow_through": 3,
        "awaiting_manager_follow_through": 4,
        "awaiting_admin_override_follow_through": 5,
    }
    return ranks.get(outcome, -1)


def _overdue_retention_breach_follow_through_completion_rank(state: str) -> int:
    ranks = {
        "completion_not_required": 0,
        "completion_monitoring_only": 1,
        "operator_completion_pending": 2,
        "owner_completion_pending": 3,
        "manager_completion_pending": 4,
        "admin_override_completion_pending": 5,
    }
    return ranks.get(state, -1)


def _overdue_retention_breach_follow_through_verification_rank(state: str) -> int:
    ranks = {
        "verification_not_required": 0,
        "verification_monitoring_only": 1,
        "operator_verification_pending": 2,
        "owner_verification_pending": 3,
        "manager_verification_pending": 4,
        "admin_override_verification_pending": 5,
    }
    return ranks.get(state, -1)


def _overdue_retention_breach_follow_through_verification_outcome_rank(
    outcome: str,
) -> int:
    ranks = {
        "verification_resolved": 0,
        "verification_monitoring_only": 1,
        "awaiting_operator_verification_outcome": 2,
        "awaiting_owner_verification_outcome": 3,
        "awaiting_manager_verification_outcome": 4,
        "awaiting_admin_override_verification_outcome": 5,
    }
    return ranks.get(outcome, -1)


def _action_priority_rank(priority: str) -> int:
    ranks = {
        "none": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
    }
    return ranks.get(priority, -1)


def _parse_as_of(value: str | None) -> datetime | dict[str, str] | None:
    if value is None:
        return None
    if not value.strip():
        return {"status": "invalid_request", "reason": "as_of must be a non-blank ISO 8601 string"}
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return {"status": "invalid_request", "reason": "as_of must be a valid ISO 8601 datetime"}
    if parsed.tzinfo is None:
        return {"status": "invalid_request", "reason": "as_of must include timezone information"}
    return parsed.astimezone(UTC)
