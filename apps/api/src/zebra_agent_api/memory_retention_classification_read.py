from __future__ import annotations

from datetime import UTC, datetime, timedelta

from zebra_agent_api.memory_inventory_review_metrics_read import (
    _age_seconds,
)


def _classify_overdue_archive_recommendation(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    decision = str(overdue_view.get("overdue_closure_decision") or "")
    priority = str(overdue_view.get("overdue_closure_priority") or "none")
    target_memory_id = overdue_view.get("overdue_closure_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "recommendation": "archive_ready",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if decision == "keep_open_for_owner_confirmation":
        return {
            "recommendation": "retain_active_until_owner_confirmation",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_confirmation_pending_blocks_archive"],
        }
    if decision == "keep_open_for_operator_completion":
        return {
            "recommendation": "retain_active_until_operator_completion",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["operator_completion_pending_blocks_archive"],
        }
    if decision == "defer_closure_until_same_day_follow_through":
        return {
            "recommendation": "revisit_archive_after_same_day_follow_through",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["same_day_follow_through_pending_blocks_archive"],
        }
    if decision == "hold_for_next_review_confirmation":
        return {
            "recommendation": "revisit_archive_after_next_review",
            "priority": "low",
            "target_memory_id": normalized_target,
            "reasons": ["next_review_confirmation_pending_blocks_archive"],
        }
    return {
        "recommendation": "keep_monitoring_without_archive",
        "priority": "low",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_archive_monitoring_recommendation"],
    }


def _classify_overdue_retention_guidance(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    recommendation = str(overdue_view.get("overdue_archive_recommendation") or "")
    priority = str(overdue_view.get("overdue_archive_priority") or "none")
    target_memory_id = overdue_view.get("overdue_archive_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "guidance": "retain_for_archive_execution",
            "priority": "none",
            "bucket": "archive_ready",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if recommendation == "retain_active_until_owner_confirmation":
        return {
            "guidance": "extend_retention_until_owner_confirmation",
            "priority": "high",
            "bucket": "extended",
            "target_memory_id": normalized_target,
            "reasons": ["owner_confirmation_pending_requires_extended_retention"],
        }
    if recommendation == "retain_active_until_operator_completion":
        return {
            "guidance": "extend_retention_until_operator_completion",
            "priority": "high" if priority == "high" else "medium",
            "bucket": "extended" if priority == "high" else "standard",
            "target_memory_id": normalized_target,
            "reasons": ["operator_completion_pending_requires_active_retention"],
        }
    if recommendation == "revisit_archive_after_same_day_follow_through":
        return {
            "guidance": "retain_until_same_day_follow_through",
            "priority": "medium",
            "bucket": "short_term",
            "target_memory_id": normalized_target,
            "reasons": ["same_day_follow_through_requires_short_term_retention"],
        }
    if recommendation == "revisit_archive_after_next_review":
        return {
            "guidance": "retain_until_next_review",
            "priority": "low",
            "bucket": "standard",
            "target_memory_id": normalized_target,
            "reasons": ["next_review_confirmation_requires_standard_retention"],
        }
    return {
        "guidance": "retain_while_monitoring",
        "priority": "low",
        "bucket": "standard",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_retention_monitoring_guidance"],
    }


def _classify_overdue_retention_window(
    *,
    overdue_view: dict[str, object],
    as_of: datetime,
) -> dict[str, object]:
    guidance = str(overdue_view.get("overdue_retention_guidance") or "")
    priority = str(overdue_view.get("overdue_retention_priority") or "none")
    target_memory_id = overdue_view.get("overdue_retention_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None
    due_at_raw = overdue_view.get("follow_up_due_at")
    anchor_at = as_of
    if isinstance(due_at_raw, str):
        try:
            anchor_at = datetime.fromisoformat(due_at_raw).astimezone(UTC)
        except ValueError:
            anchor_at = as_of

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "window": "archive_immediately",
            "priority": "none",
            "due_at": as_of.isoformat(),
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if guidance == "extend_retention_until_owner_confirmation":
        return {
            "window": "review_within_7d",
            "priority": "high",
            "due_at": (anchor_at + timedelta(days=7)).isoformat(),
            "target_memory_id": normalized_target,
            "reasons": ["owner_confirmation_pending_requires_weekly_review_window"],
        }
    if guidance == "extend_retention_until_operator_completion":
        if priority == "high":
            return {
                "window": "review_within_1d",
                "priority": "high",
                "due_at": (anchor_at + timedelta(days=1)).isoformat(),
                "target_memory_id": normalized_target,
                "reasons": ["high_priority_operator_completion_requires_next_day_review"],
            }
        return {
            "window": "review_within_3d",
            "priority": "medium",
            "due_at": (anchor_at + timedelta(days=3)).isoformat(),
            "target_memory_id": normalized_target,
            "reasons": ["operator_completion_requires_short_review_window"],
        }
    if guidance == "retain_until_same_day_follow_through":
        return {
            "window": "review_within_12h",
            "priority": "medium",
            "due_at": (anchor_at + timedelta(hours=12)).isoformat(),
            "target_memory_id": normalized_target,
            "reasons": ["same_day_follow_through_requires_same_day_review_window"],
        }
    if guidance == "retain_until_next_review":
        return {
            "window": "review_within_7d",
            "priority": "low",
            "due_at": (anchor_at + timedelta(days=7)).isoformat(),
            "target_memory_id": normalized_target,
            "reasons": ["next_review_confirmation_requires_weekly_review_window"],
        }
    return {
        "window": "review_within_7d",
        "priority": "low",
        "due_at": (anchor_at + timedelta(days=7)).isoformat(),
        "target_memory_id": normalized_target,
        "reasons": ["fallback_retention_window_review"],
    }


def _classify_overdue_retention_breach(
    *,
    overdue_view: dict[str, object],
    as_of: datetime,
) -> dict[str, object]:
    window = str(overdue_view.get("overdue_retention_window") or "")
    priority = str(overdue_view.get("overdue_retention_window_priority") or "none")
    due_at = overdue_view.get("overdue_retention_window_due_at")
    target_memory_id = overdue_view.get("overdue_retention_window_target_memory_id")
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None
    oldest_pending_age_days = overdue_view.get("oldest_pending_age_days")
    normalized_age_days = oldest_pending_age_days if isinstance(oldest_pending_age_days, int) else 0
    oldest_pending_captured_at = overdue_view.get("oldest_pending_captured_at")
    breach_anchor = None
    if isinstance(oldest_pending_captured_at, str):
        try:
            breach_anchor = datetime.fromisoformat(oldest_pending_captured_at).astimezone(UTC)
        except ValueError:
            breach_anchor = None

    def breach_due_at(offset: timedelta) -> str:
        if breach_anchor is not None:
            return (breach_anchor + offset).isoformat()
        return due_at if isinstance(due_at, str) else as_of.isoformat()

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "breach": "not_applicable",
            "priority": "none",
            "due_at": due_at if isinstance(due_at, str) else as_of.isoformat(),
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if window == "review_within_12h":
        if normalized_age_days < 1:
            return {
                "breach": "within_retention_window",
                "priority": "none",
                "due_at": due_at if isinstance(due_at, str) else as_of.isoformat(),
                "target_memory_id": normalized_target,
                "reasons": ["retention_window_not_yet_breached"],
            }
        return {
            "breach": "same_day_window_breached",
            "priority": "high",
            "due_at": breach_due_at(timedelta(hours=12)),
            "target_memory_id": normalized_target,
            "reasons": ["same_day_retention_window_was_missed"],
        }
    if window == "review_within_1d":
        if normalized_age_days < 2:
            return {
                "breach": "within_retention_window",
                "priority": "none",
                "due_at": due_at if isinstance(due_at, str) else as_of.isoformat(),
                "target_memory_id": normalized_target,
                "reasons": ["retention_window_not_yet_breached"],
            }

        return {
            "breach": "next_day_window_breached",
            "priority": "high",
            "due_at": breach_due_at(timedelta(days=1)),
            "target_memory_id": normalized_target,
            "reasons": ["next_day_retention_window_was_missed"],
        }
    if window == "review_within_3d":
        if normalized_age_days < 4:
            return {
                "breach": "within_retention_window",
                "priority": "none",
                "due_at": due_at if isinstance(due_at, str) else as_of.isoformat(),
                "target_memory_id": normalized_target,
                "reasons": ["retention_window_not_yet_breached"],
            }
        return {
            "breach": "short_window_breached",
            "priority": "high" if priority == "high" else "medium",
            "due_at": breach_due_at(timedelta(days=3)),
            "target_memory_id": normalized_target,
            "reasons": ["short_retention_window_was_missed"],
        }
    if normalized_age_days >= 21:
        return {
            "breach": "extended_window_breached",
            "priority": "medium",
            "due_at": breach_due_at(timedelta(days=21)),
            "target_memory_id": normalized_target,
            "reasons": ["extended_retention_window_was_missed"],
        }
    if normalized_age_days >= 14:
        return {
            "breach": "weekly_window_breached",
            "priority": "low",
            "due_at": breach_due_at(timedelta(days=14)),
            "target_memory_id": normalized_target,
            "reasons": ["retention_review_window_was_missed"],
        }
    return {
        "breach": "within_retention_window",
        "priority": "none",
        "due_at": due_at if isinstance(due_at, str) else as_of.isoformat(),
        "target_memory_id": normalized_target,
        "reasons": ["retention_window_not_yet_breached"],
    }


def _classify_overdue_retention_breach_aging(
    *,
    overdue_view: dict[str, object],
    as_of: datetime,
) -> dict[str, object]:
    breach = str(overdue_view.get("overdue_retention_breach") or "")
    due_at = overdue_view.get("overdue_retention_breach_due_at")
    if breach in {"not_applicable", "within_retention_window"}:
        return {
            "bucket": "not_breached",
            "age_seconds": 0,
            "age_days": 0,
            "reasons": ["retention_breach_not_active"],
        }
    if not isinstance(due_at, str):
        return {
            "bucket": "unknown_breach_age",
            "age_seconds": 0,
            "age_days": 0,
            "reasons": ["missing_retention_breach_due_at"],
        }
    try:
        due_timestamp = datetime.fromisoformat(due_at).astimezone(UTC)
    except ValueError:
        return {
            "bucket": "unknown_breach_age",
            "age_seconds": 0,
            "age_days": 0,
            "reasons": ["invalid_retention_breach_due_at"],
        }
    age_seconds = _age_seconds(due_timestamp, as_of)
    age_days = age_seconds // 86_400
    if age_seconds < 86_400:
        bucket = "lt_1d_breached"
    elif age_seconds < 259_200:
        bucket = "gte_1d_lt_3d_breached"
    elif age_seconds < 604_800:
        bucket = "gte_3d_lt_7d_breached"
    else:
        bucket = "gte_7d_breached"
    return {
        "bucket": bucket,
        "age_seconds": age_seconds,
        "age_days": age_days,
        "reasons": ["retention_breach_age_classified"],
    }
