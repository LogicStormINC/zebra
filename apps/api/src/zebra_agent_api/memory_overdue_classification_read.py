from __future__ import annotations


def _classify_overdue_intervention_hint(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    signal = str(overdue_view.get("overdue_trend_signal") or "")
    priority = str(overdue_view.get("follow_up_overdue_priority") or "none")
    target_memory_id = overdue_view.get("follow_up_overdue_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "hint": "no_intervention_needed",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if signal == "critical_overdue":
        return {
            "hint": "assign_scope_owner",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["critical_overdue_requires_explicit_owner"],
        }
    if signal == "escalating_overdue":
        return {
            "hint": "review_now",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["escalating_overdue_requires_immediate_review"],
        }
    if signal == "persistent_overdue":
        return {
            "hint": "same_day_review_burst",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["persistent_overdue_requires_same_day_attention"],
        }
    if signal == "emerging_overdue":
        return {
            "hint": "queue_next_review_window",
            "priority": "low",
            "target_memory_id": normalized_target,
            "reasons": ["emerging_overdue_can_be_handled_in_next_window"],
        }
    return {
        "hint": "monitor_scope",
        "priority": "low",
        "target_memory_id": normalized_target,
        "reasons": ["trend_signal_unknown_monitor_scope"],
    }


def _classify_overdue_escalation_lane(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    hint = str(overdue_view.get("overdue_intervention_hint") or "")
    priority = str(overdue_view.get("overdue_intervention_priority") or "none")
    target_memory_id = overdue_view.get("overdue_intervention_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "lane": "no_escalation",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if hint == "assign_scope_owner":
        return {
            "lane": "manager_escalation",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["critical_scope_requires_manager_escalation"],
        }
    if hint == "review_now":
        return {
            "lane": "immediate_operator_escalation",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["review_now_requires_immediate_operator_escalation"],
        }
    if hint == "same_day_review_burst":
        return {
            "lane": "same_day_operator_lane",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["same_day_review_burst_maps_to_same_day_operator_lane"],
        }
    if hint == "queue_next_review_window":
        return {
            "lane": "local_queue_lane",
            "priority": "low",
            "target_memory_id": normalized_target,
            "reasons": ["next_review_window_remains_in_local_queue"],
        }
    return {
        "lane": "monitoring_lane",
        "priority": "low",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_monitoring_lane"],
    }


def _classify_overdue_recovery_path(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    lane = str(overdue_view.get("overdue_escalation_lane") or "")
    priority = str(overdue_view.get("overdue_escalation_priority") or "none")
    target_memory_id = overdue_view.get("overdue_escalation_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "path": "no_recovery_needed",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if lane == "manager_escalation":
        return {
            "path": "owner_assignment_recovery_plan",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["manager_escalation_requires_named_recovery_plan"],
        }
    if lane == "immediate_operator_escalation":
        return {
            "path": "immediate_operator_recovery",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["immediate_operator_escalation_requires_recovery_execution"],
        }
    if lane == "same_day_operator_lane":
        return {
            "path": "same_day_recovery_burst",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["same_day_operator_lane_maps_to_same_day_recovery_burst"],
        }
    if lane == "local_queue_lane":
        return {
            "path": "next_local_review_recovery",
            "priority": "low",
            "target_memory_id": normalized_target,
            "reasons": ["local_queue_lane_maps_to_next_local_review_recovery"],
        }
    return {
        "path": "monitor_recovery_readiness",
        "priority": "low",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_recovery_monitoring_path"],
    }


def _classify_overdue_resolution_checkpoint(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    path = str(overdue_view.get("overdue_recovery_path") or "")
    priority = str(overdue_view.get("overdue_recovery_priority") or "none")
    target_memory_id = overdue_view.get("overdue_recovery_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "checkpoint": "no_resolution_checkpoint",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if path == "owner_assignment_recovery_plan":
        return {
            "checkpoint": "owner_confirmation_checkpoint",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_assignment_requires_resolution_confirmation"],
        }
    if path == "immediate_operator_recovery":
        return {
            "checkpoint": "operator_completion_checkpoint",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["immediate_operator_recovery_requires_completion_checkpoint"],
        }
    if path == "same_day_recovery_burst":
        return {
            "checkpoint": "same_day_resolution_checkpoint",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["same_day_recovery_burst_maps_to_same_day_resolution_checkpoint"],
        }
    if path == "next_local_review_recovery":
        return {
            "checkpoint": "next_review_confirmation_checkpoint",
            "priority": "low",
            "target_memory_id": normalized_target,
            "reasons": ["next_local_review_recovery_maps_to_next_review_confirmation"],
        }
    return {
        "checkpoint": "monitor_resolution_readiness",
        "priority": "low",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_resolution_monitoring_checkpoint"],
    }


def _classify_overdue_resolution_outcome(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    checkpoint = str(overdue_view.get("overdue_resolution_checkpoint") or "")
    priority = str(overdue_view.get("overdue_resolution_priority") or "none")
    target_memory_id = overdue_view.get("overdue_resolution_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "outcome": "resolved",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if checkpoint == "owner_confirmation_checkpoint":
        return {
            "outcome": "awaiting_owner_confirmation",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_confirmation_checkpoint_requires_explicit_confirmation"],
        }
    if checkpoint == "operator_completion_checkpoint":
        return {
            "outcome": "awaiting_operator_completion",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["operator_completion_checkpoint_requires_completion"],
        }
    if checkpoint == "same_day_resolution_checkpoint":
        return {
            "outcome": "same_day_follow_through",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["same_day_resolution_checkpoint_requires_same_day_follow_through"],
        }
    if checkpoint == "next_review_confirmation_checkpoint":
        return {
            "outcome": "pending_next_review_confirmation",
            "priority": "low",
            "target_memory_id": normalized_target,
            "reasons": ["next_review_confirmation_checkpoint_requires_next_review"],
        }
    return {
        "outcome": "monitoring_only",
        "priority": "low",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_resolution_outcome_monitoring"],
    }


def _classify_overdue_closure_decision(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    outcome = str(overdue_view.get("overdue_resolution_outcome") or "")
    priority = str(overdue_view.get("overdue_resolution_outcome_priority") or "none")
    target_memory_id = overdue_view.get("overdue_resolution_outcome_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "decision": "close_scope",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if outcome == "awaiting_owner_confirmation":
        return {
            "decision": "keep_open_for_owner_confirmation",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_confirmation_pending_prevents_closure"],
        }
    if outcome == "awaiting_operator_completion":
        return {
            "decision": "keep_open_for_operator_completion",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["operator_completion_pending_prevents_closure"],
        }
    if outcome == "same_day_follow_through":
        return {
            "decision": "defer_closure_until_same_day_follow_through",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["same_day_follow_through_requires_completion_before_closure"],
        }
    if outcome == "pending_next_review_confirmation":
        return {
            "decision": "hold_for_next_review_confirmation",
            "priority": "low",
            "target_memory_id": normalized_target,
            "reasons": ["next_review_confirmation_pending_prevents_closure"],
        }
    return {
        "decision": "continue_monitoring_without_closure",
        "priority": "low",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_closure_decision_monitoring"],
    }
