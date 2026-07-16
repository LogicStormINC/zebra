from __future__ import annotations


def _classify_overdue_retention_breach_action(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    bucket = str(overdue_view.get("overdue_retention_breach_age_bucket") or "")
    target_memory_id = overdue_view.get("overdue_retention_breach_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if bucket == "not_breached":
        return {
            "action": "no_retention_action",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["retention_breach_not_active"],
        }
    if bucket == "unknown_breach_age":
        return {
            "action": "inspect_breach_timestamps",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["breach_age_unknown_requires_timestamp_review"],
        }
    if bucket == "lt_1d_breached":
        return {
            "action": "queue_immediate_retention_review",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["new_retention_breach_requires_immediate_review"],
        }
    if bucket == "gte_1d_lt_3d_breached":
        return {
            "action": "assign_retention_owner",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["retention_breach_persisted_multiple_days"],
        }
    if bucket == "gte_3d_lt_7d_breached":
        return {
            "action": "escalate_retention_decision",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["retention_breach_escalating_beyond_local_review_window"],
        }
    return {
        "action": "force_archive_or_override",
        "priority": "high",
        "target_memory_id": normalized_target,
        "reasons": ["retention_breach_exceeded_extended_grace_window"],
    }


def _classify_overdue_retention_breach_lane(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    action = str(overdue_view.get("overdue_retention_breach_action") or "")
    target_memory_id = overdue_view.get("overdue_retention_breach_action_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if action == "no_retention_action":
        return {
            "lane": "no_retention_lane",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["retention_breach_not_active"],
        }
    if action == "inspect_breach_timestamps":
        return {
            "lane": "operator_timestamp_review_lane",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["timestamp_review_needed_before_routing"],
        }
    if action == "queue_immediate_retention_review":
        return {
            "lane": "operator_retention_review_lane",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["immediate_review_stays_with_operator_lane"],
        }
    if action == "assign_retention_owner":
        return {
            "lane": "owner_assignment_lane",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["persistent_breach_requires_explicit_owner_lane"],
        }
    if action == "escalate_retention_decision":
        return {
            "lane": "manager_retention_escalation_lane",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["escalated_breach_requires_manager_lane"],
        }
    return {
        "lane": "emergency_retention_override_lane",
        "priority": "high",
        "target_memory_id": normalized_target,
        "reasons": ["extended_breach_requires_override_lane"],
    }


def _classify_overdue_retention_breach_owner_target(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    lane = str(overdue_view.get("overdue_retention_breach_lane") or "")
    target_memory_id = overdue_view.get("overdue_retention_breach_lane_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if lane == "no_retention_lane":
        return {
            "owner_target": "no_owner_assignment",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["retention_breach_not_active"],
        }
    if lane == "operator_timestamp_review_lane":
        return {
            "owner_target": "memory_operator",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["timestamp_review_stays_with_memory_operator"],
        }
    if lane == "operator_retention_review_lane":
        return {
            "owner_target": "memory_operator",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["retention_review_stays_with_memory_operator"],
        }
    if lane == "owner_assignment_lane":
        return {
            "owner_target": "scope_owner",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_assignment_lane_maps_to_scope_owner"],
        }
    if lane == "manager_retention_escalation_lane":
        return {
            "owner_target": "retention_manager",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["manager_lane_maps_to_retention_manager"],
        }
    return {
        "owner_target": "retention_admin",
        "priority": "high",
        "target_memory_id": normalized_target,
        "reasons": ["override_lane_maps_to_retention_admin"],
    }


def _classify_overdue_retention_breach_follow_through_mode(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    owner_target = str(overdue_view.get("overdue_retention_breach_owner_target") or "")
    target_memory_id = overdue_view.get("overdue_retention_breach_owner_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if owner_target == "no_owner_assignment":
        return {
            "mode": "no_follow_through_needed",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["retention_breach_not_active"],
        }
    if owner_target == "memory_operator":
        return {
            "mode": "operator_review_follow_through",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["memory_operator_handles_direct_review_follow_through"],
        }
    if owner_target == "scope_owner":
        return {
            "mode": "owner_confirmation_follow_through",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["scope_owner_must_confirm_retention_direction"],
        }
    if owner_target == "retention_manager":
        return {
            "mode": "manager_decision_follow_through",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["retention_manager_must_make_escalated_decision"],
        }
    return {
        "mode": "admin_override_follow_through",
        "priority": "high",
        "target_memory_id": normalized_target,
        "reasons": ["retention_admin_must_execute_override_path"],
    }


def _classify_overdue_retention_breach_follow_through_outcome(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    mode = str(overdue_view.get("overdue_retention_breach_follow_through_mode") or "")
    priority = str(overdue_view.get("overdue_retention_breach_follow_through_priority") or "none")
    target_memory_id = overdue_view.get("overdue_retention_breach_follow_through_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "outcome": "no_follow_through_outstanding",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if mode == "operator_review_follow_through":
        return {
            "outcome": "awaiting_operator_follow_through",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["operator_review_follow_through_requires_operator_completion"],
        }
    if mode == "owner_confirmation_follow_through":
        return {
            "outcome": "awaiting_owner_follow_through",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_confirmation_follow_through_requires_owner_confirmation"],
        }
    if mode == "manager_decision_follow_through":
        return {
            "outcome": "awaiting_manager_follow_through",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["manager_decision_follow_through_requires_manager_decision"],
        }
    if mode == "admin_override_follow_through":
        return {
            "outcome": "awaiting_admin_override_follow_through",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["admin_override_follow_through_requires_admin_override"],
        }
    return {
        "outcome": "follow_through_monitoring_only",
        "priority": "low" if priority != "none" else "none",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_follow_through_outcome_monitoring"],
    }


def _classify_overdue_retention_breach_follow_through_completion_state(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    outcome = str(overdue_view.get("overdue_retention_breach_follow_through_outcome") or "")
    priority = str(
        overdue_view.get("overdue_retention_breach_follow_through_outcome_priority") or "none"
    )
    target_memory_id = overdue_view.get("overdue_retention_breach_follow_through_outcome_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "state": "completion_not_required",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if outcome == "awaiting_operator_follow_through":
        return {
            "state": "operator_completion_pending",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["operator_follow_through_must_complete_before_closure"],
        }
    if outcome == "awaiting_owner_follow_through":
        return {
            "state": "owner_completion_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_follow_through_must_complete_before_closure"],
        }
    if outcome == "awaiting_manager_follow_through":
        return {
            "state": "manager_completion_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["manager_follow_through_must_complete_before_closure"],
        }
    if outcome == "awaiting_admin_override_follow_through":
        return {
            "state": "admin_override_completion_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["admin_override_follow_through_must_complete_before_closure"],
        }
    return {
        "state": "completion_monitoring_only",
        "priority": "low" if priority != "none" else "none",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_follow_through_completion_monitoring"],
    }
