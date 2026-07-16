from __future__ import annotations


def _classify_overdue_retention_breach_follow_through_verification_state(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    completion_state = str(
        overdue_view.get("overdue_retention_breach_follow_through_completion_state") or ""
    )
    priority = str(
        overdue_view.get("overdue_retention_breach_follow_through_completion_priority") or "none"
    )
    target_memory_id = overdue_view.get(
        "overdue_retention_breach_follow_through_completion_memory_id"
    )
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "state": "verification_not_required",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if completion_state == "operator_completion_pending":
        return {
            "state": "operator_verification_pending",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["operator_completion_requires_verification_before_signoff"],
        }
    if completion_state == "owner_completion_pending":
        return {
            "state": "owner_verification_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_completion_requires_verification_before_signoff"],
        }
    if completion_state == "manager_completion_pending":
        return {
            "state": "manager_verification_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["manager_completion_requires_verification_before_signoff"],
        }
    if completion_state == "admin_override_completion_pending":
        return {
            "state": "admin_override_verification_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["admin_override_completion_requires_verification_before_signoff"],
        }
    return {
        "state": "verification_monitoring_only",
        "priority": "low" if priority != "none" else "none",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_follow_through_verification_monitoring"],
    }


def _classify_overdue_retention_breach_follow_through_verification_outcome(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    state = str(
        overdue_view.get("overdue_retention_breach_follow_through_verification_state") or ""
    )
    priority = str(
        overdue_view.get("overdue_retention_breach_follow_through_verification_priority") or "none"
    )
    target_memory_id = overdue_view.get(
        "overdue_retention_breach_follow_through_verification_memory_id"
    )
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "outcome": "verification_resolved",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if state == "admin_override_verification_pending":
        return {
            "outcome": "awaiting_admin_override_verification_outcome",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["admin_override_verification_pending_requires_explicit_outcome"],
        }
    if state == "manager_verification_pending":
        return {
            "outcome": "awaiting_manager_verification_outcome",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["manager_verification_pending_requires_explicit_outcome"],
        }
    if state == "owner_verification_pending":
        return {
            "outcome": "awaiting_owner_verification_outcome",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["owner_verification_pending_requires_explicit_outcome"],
        }
    if state == "operator_verification_pending":
        return {
            "outcome": "awaiting_operator_verification_outcome",
            "priority": "medium" if priority == "medium" else "low",
            "target_memory_id": normalized_target,
            "reasons": ["operator_verification_pending_requires_explicit_outcome"],
        }
    if state == "verification_not_required":
        return {
            "outcome": "verification_resolved",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["verification_not_required"],
        }
    return {
        "outcome": "verification_monitoring_only",
        "priority": "low" if priority != "none" else "none",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_verification_outcome_monitoring"],
    }


def _int_field(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0
