from __future__ import annotations

from datetime import UTC, datetime, timedelta

from zebra_agent_api.memory_follow_through_classification_read import (
    _int_field,
)
from zebra_agent_api.memory_inventory_review_metrics_read import (
    _age_seconds,
)


def _classify_action_hint(pressure: dict[str, object]) -> dict[str, object]:
    level = str(pressure.get("pressure_level") or "")
    pending_count = _int_field(pressure, "pending_count")
    reviewed_last_24h_count = _int_field(pressure, "reviewed_last_24h_count")
    oldest_pending_memory_id = pressure.get("oldest_pending_memory_id")
    raw_pressure_reasons = pressure.get("pressure_reasons")
    pressure_reasons = (
        [reason for reason in raw_pressure_reasons if isinstance(reason, str)]
        if isinstance(raw_pressure_reasons, list)
        else []
    )
    target_memory_id = (
        oldest_pending_memory_id if isinstance(oldest_pending_memory_id, str) else None
    )

    if level == "clear" or pending_count == 0:
        return {
            "hint": "no_action_needed",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["backlog_clear"],
        }
    if level == "high" and isinstance(oldest_pending_memory_id, str):
        return {
            "hint": "review_oldest_pending",
            "priority": "high",
            "target_memory_id": oldest_pending_memory_id,
            "reasons": pressure_reasons or ["high_pressure_backlog"],
        }
    if level == "elevated" and reviewed_last_24h_count == 0:
        return {
            "hint": "restart_review_queue",
            "priority": "medium",
            "target_memory_id": target_memory_id,
            "reasons": pressure_reasons or ["stalled_review_flow"],
        }
    if pending_count > 0:
        return {
            "hint": "continue_review_flow",
            "priority": "low",
            "target_memory_id": target_memory_id,
            "reasons": ["backlog_under_control"],
        }
    return {
        "hint": "monitor_scope",
        "priority": "low",
        "target_memory_id": None,
        "reasons": ["monitoring_only"],
    }


def _classify_escalation_recommendation(action_view: dict[str, object]) -> dict[str, object]:
    level = str(action_view.get("pressure_level") or "")
    action_hint = str(action_view.get("action_hint") or "")
    oldest_pending_age_days = _int_field(action_view, "oldest_pending_age_days")
    reviewed_last_24h_count = _int_field(action_view, "reviewed_last_24h_count")
    reviewed_last_7d_count = _int_field(action_view, "reviewed_last_7d_count")
    target_memory_id = action_view.get("action_target_memory_id")
    raw_pressure_reasons = action_view.get("pressure_reasons")
    pressure_reasons = (
        [reason for reason in raw_pressure_reasons if isinstance(reason, str)]
        if isinstance(raw_pressure_reasons, list)
        else []
    )

    if action_hint == "no_action_needed" or level == "clear":
        return {
            "recommendation": "no_escalation_needed",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["backlog_clear"],
        }
    if level == "high" and oldest_pending_age_days >= 7 and reviewed_last_7d_count == 0:
        return {
            "recommendation": "escalate_stalled_scope",
            "priority": "high",
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "reasons": pressure_reasons or ["stalled_high_pressure"],
        }
    if level == "high":
        return {
            "recommendation": "schedule_same_day_review_burst",
            "priority": "medium",
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "reasons": pressure_reasons or ["high_pressure_requires_review_burst"],
        }
    if action_hint == "restart_review_queue" and reviewed_last_24h_count == 0:
        return {
            "recommendation": "monitor_until_next_review_window",
            "priority": "low",
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "reasons": ["awaiting_review_restart"],
        }
    return {
        "recommendation": "no_escalation_needed",
        "priority": "none",
        "target_memory_id": None,
        "reasons": ["local_review_flow_sufficient"],
    }


def _classify_follow_up_window(
    escalation_view: dict[str, object],
    *,
    as_of: datetime,
) -> dict[str, object]:
    recommendation = str(escalation_view.get("escalation_recommendation") or "")
    target_memory_id = escalation_view.get("escalation_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if recommendation == "escalate_stalled_scope":
        return {
            "window": "immediate_follow_up",
            "priority": "high",
            "due_at": as_of.isoformat(),
            "target_memory_id": normalized_target,
            "reasons": ["escalation_open_now"],
        }
    if recommendation == "schedule_same_day_review_burst":
        return {
            "window": "same_day_follow_up",
            "priority": "medium",
            "due_at": (as_of + timedelta(hours=4)).isoformat(),
            "target_memory_id": normalized_target,
            "reasons": ["same_day_review_burst_due"],
        }
    if recommendation == "monitor_until_next_review_window":
        return {
            "window": "next_24h_review_window",
            "priority": "low",
            "due_at": (as_of + timedelta(days=1)).isoformat(),
            "target_memory_id": normalized_target,
            "reasons": ["recheck_after_local_review_window"],
        }
    return {
        "window": "next_7d_review_window",
        "priority": "none",
        "due_at": (as_of + timedelta(days=7)).isoformat(),
        "target_memory_id": None,
        "reasons": ["routine_follow_up_only"],
    }


def _classify_follow_up_overdue_flag(
    follow_up_view: dict[str, object],
    *,
    as_of: datetime,
) -> dict[str, object]:
    due_at_raw = follow_up_view.get("follow_up_due_at")
    target_memory_id = follow_up_view.get("follow_up_target_memory_id")
    priority = str(follow_up_view.get("follow_up_priority") or "none")
    if not isinstance(due_at_raw, str):
        return {
            "overdue": False,
            "priority": "none",
            "overdue_since": None,
            "target_memory_id": None,
            "reasons": ["missing_follow_up_due_at"],
        }
    try:
        due_at = datetime.fromisoformat(due_at_raw).astimezone(UTC)
    except ValueError:
        return {
            "overdue": False,
            "priority": "none",
            "overdue_since": None,
            "target_memory_id": None,
            "reasons": ["invalid_follow_up_due_at"],
        }
    is_overdue = due_at <= as_of
    return {
        "overdue": is_overdue,
        "priority": priority if is_overdue else "none",
        "overdue_since": due_at.isoformat() if is_overdue else None,
        "target_memory_id": target_memory_id if isinstance(target_memory_id, str) else None,
        "reasons": ["follow_up_due"] if is_overdue else ["follow_up_not_due"],
    }


def _classify_overdue_age_bucket(
    overdue_view: dict[str, object],
    *,
    as_of: datetime,
) -> dict[str, object]:
    overdue = overdue_view.get("follow_up_overdue")
    overdue_since_raw = overdue_view.get("follow_up_overdue_since")
    if overdue is not True or not isinstance(overdue_since_raw, str):
        return {
            "bucket": "not_overdue",
            "age_seconds": 0,
            "age_days": 0,
            "reasons": ["follow_up_not_overdue"],
        }
    try:
        overdue_since = datetime.fromisoformat(overdue_since_raw).astimezone(UTC)
    except ValueError:
        return {
            "bucket": "unknown_overdue_age",
            "age_seconds": 0,
            "age_days": 0,
            "reasons": ["invalid_overdue_since"],
        }
    age_seconds = _age_seconds(overdue_since, as_of)
    age_days = age_seconds // 86_400
    if age_seconds < 86_400:
        bucket = "lt_1d_overdue"
    elif age_seconds < 259_200:
        bucket = "gte_1d_lt_3d_overdue"
    elif age_seconds < 604_800:
        bucket = "gte_3d_lt_7d_overdue"
    else:
        bucket = "gte_7d_overdue"
    return {
        "bucket": bucket,
        "age_seconds": age_seconds,
        "age_days": age_days,
        "reasons": ["overdue_age_classified"],
    }


def _classify_overdue_trend_signal(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    bucket = overdue_view.get("overdue_age_bucket")
    if not isinstance(bucket, str):
        return {
            "signal": "unknown_trend",
            "rank": 0,
            "reasons": ["missing_overdue_age_bucket"],
        }
    mapping = {
        "not_overdue": ("clear", 0, ["follow_up_not_overdue"]),
        "unknown_overdue_age": ("unknown_trend", 0, ["unknown_overdue_age"]),
        "lt_1d_overdue": ("emerging_overdue", 1, ["new_overdue_scope"]),
        "gte_1d_lt_3d_overdue": (
            "persistent_overdue",
            2,
            ["overdue_persisting_multiple_days"],
        ),
        "gte_3d_lt_7d_overdue": (
            "escalating_overdue",
            3,
            ["overdue_escalating_beyond_local_window"],
        ),
        "gte_7d_overdue": (
            "critical_overdue",
            4,
            ["overdue_past_critical_threshold"],
        ),
    }
    signal, rank, reasons = mapping.get(
        bucket,
        ("unknown_trend", 0, ["unmapped_overdue_age_bucket"]),
    )
    return {
        "signal": signal,
        "rank": rank,
        "reasons": reasons,
    }
