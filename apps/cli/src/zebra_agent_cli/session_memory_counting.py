from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_core.domain.events import SessionEvent
from zebra_agent_api.session_context import session_workspace_root

from zebra_agent_cli.session_memory_ranking import (
    _pressure_rank,
)


def _session_workspace_root(events: Sequence[SessionEvent]) -> Path | None:
    return session_workspace_root(list(events))


def _sum_pending_counts(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        pending_count = scope.get("pending_count")
        if isinstance(pending_count, int) and not isinstance(pending_count, bool):
            total += pending_count
    return total


def _sum_reviewed_counts(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        reviewed_count = scope.get("reviewed_count")
        if isinstance(reviewed_count, int) and not isinstance(reviewed_count, bool):
            total += reviewed_count
    return total


def _sum_status_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("review_status_counts")
        if not isinstance(counts, dict):
            continue
        for status, count in counts.items():
            if not isinstance(status, str):
                continue
            if not isinstance(count, int) or isinstance(count, bool):
                continue
            totals[status] = totals.get(status, 0) + count
    return totals


def _sum_age_bucket_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals = {
        "lt_1d": 0,
        "gte_1d_lt_3d": 0,
        "gte_3d_lt_7d": 0,
        "gte_7d": 0,
    }
    for scope in scopes:
        counts = scope.get("pending_age_buckets")
        if not isinstance(counts, dict):
            continue
        for bucket_name in totals:
            count = counts.get(bucket_name)
            if isinstance(count, int) and not isinstance(count, bool):
                totals[bucket_name] += count
    return totals


def _sum_recent_review_counts(
    scopes: list[dict[str, object]],
    field_name: str,
) -> int:
    total = 0
    for scope in scopes:
        count = scope.get(field_name)
        if isinstance(count, int) and not isinstance(count, bool):
            total += count
    return total


def _latest_review_scope(
    scopes: list[dict[str, object]],
) -> dict[str, str] | None:
    latest: dict[str, str] | None = None
    for scope in scopes:
        recorded_at = scope.get("latest_reviewed_at")
        status = scope.get("latest_review_status")
        operator = scope.get("latest_review_operator")
        window = scope.get("latest_review_window")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        if not (
            isinstance(recorded_at, str)
            and isinstance(status, str)
            and isinstance(operator, str)
            and isinstance(window, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
        ):
            continue
        candidate = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "recorded_at": recorded_at,
            "status": status,
            "operator": operator,
            "window": window,
        }
        if latest is None or recorded_at > latest["recorded_at"]:
            latest = candidate
    return latest


def _sum_pressure_level_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        level = scope.get("pressure_level")
        if not isinstance(level, str):
            continue
        totals[level] = totals.get(level, 0) + 1
    return totals


def _highest_pressure_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        level = scope.get("pressure_level")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        reasons = scope.get("pressure_reasons")
        if not (
            isinstance(level, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "pressure_level": level,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "pressure_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _pressure_rank(level) > _pressure_rank(
            str(highest["pressure_level"])
        ):
            highest = candidate
    return highest


def _sum_action_hint_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        hint = scope.get("action_hint")
        if not isinstance(hint, str):
            continue
        totals[hint] = totals.get(hint, 0) + 1
    return totals


def _sum_escalation_recommendation_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        recommendation = scope.get("escalation_recommendation")
        if not isinstance(recommendation, str):
            continue
        totals[recommendation] = totals.get(recommendation, 0) + 1
    return totals


def _sum_follow_up_window_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        window = scope.get("follow_up_window")
        if not isinstance(window, str):
            continue
        totals[window] = totals.get(window, 0) + 1
    return totals


def _sum_overdue_scope_count(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        if scope.get("follow_up_overdue") is True:
            total += 1
    return total


def _sum_overdue_age_bucket_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        bucket = scope.get("overdue_age_bucket")
        if not isinstance(bucket, str):
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
    return totals


def _sum_overdue_memory_type_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("overdue_memory_type_counts")
        if not isinstance(counts, dict):
            continue
        for memory_type, count in counts.items():
            if not isinstance(memory_type, str) or not isinstance(count, int):
                continue
            totals[memory_type] = totals.get(memory_type, 0) + count
    return totals


def _sum_overdue_memory_visibility_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("overdue_memory_visibility_counts")
        if not isinstance(counts, dict):
            continue
        for visibility, count in counts.items():
            if not isinstance(visibility, str) or not isinstance(count, int):
                continue
            totals[visibility] = totals.get(visibility, 0) + count
    return totals


def _sum_overdue_trend_signal_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        signal = scope.get("overdue_trend_signal")
        if not isinstance(signal, str):
            continue
        totals[signal] = totals.get(signal, 0) + 1
    return totals


def _sum_overdue_intervention_hint_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        hint = scope.get("overdue_intervention_hint")
        if not isinstance(hint, str):
            continue
        totals[hint] = totals.get(hint, 0) + 1
    return totals


def _sum_overdue_escalation_lane_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        lane = scope.get("overdue_escalation_lane")
        if not isinstance(lane, str):
            continue
        totals[lane] = totals.get(lane, 0) + 1
    return totals


def _sum_overdue_recovery_path_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        path = scope.get("overdue_recovery_path")
        if not isinstance(path, str):
            continue
        totals[path] = totals.get(path, 0) + 1
    return totals


def _sum_overdue_resolution_checkpoint_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        checkpoint = scope.get("overdue_resolution_checkpoint")
        if not isinstance(checkpoint, str):
            continue
        totals[checkpoint] = totals.get(checkpoint, 0) + 1
    return totals


def _sum_overdue_resolution_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get("overdue_resolution_outcome")
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _sum_overdue_closure_decision_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        decision = scope.get("overdue_closure_decision")
        if not isinstance(decision, str):
            continue
        totals[decision] = totals.get(decision, 0) + 1
    return totals


def _sum_overdue_archive_recommendation_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        recommendation = scope.get("overdue_archive_recommendation")
        if not isinstance(recommendation, str):
            continue
        totals[recommendation] = totals.get(recommendation, 0) + 1
    return totals


def _sum_overdue_retention_guidance_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        guidance = scope.get("overdue_retention_guidance")
        if not isinstance(guidance, str):
            continue
        totals[guidance] = totals.get(guidance, 0) + 1
    return totals


def _sum_overdue_retention_window_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        window = scope.get("overdue_retention_window")
        if not isinstance(window, str):
            continue
        totals[window] = totals.get(window, 0) + 1
    return totals


def _sum_overdue_retention_breach_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        breach = scope.get("overdue_retention_breach")
        if not isinstance(breach, str):
            continue
        totals[breach] = totals.get(breach, 0) + 1
    return totals


def _sum_overdue_retention_breach_age_bucket_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        bucket = scope.get("overdue_retention_breach_age_bucket")
        if not isinstance(bucket, str):
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
    return totals


def _sum_overdue_retention_breach_action_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        action = scope.get("overdue_retention_breach_action")
        if not isinstance(action, str):
            continue
        totals[action] = totals.get(action, 0) + 1
    return totals


def _sum_overdue_retention_breach_lane_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        lane = scope.get("overdue_retention_breach_lane")
        if not isinstance(lane, str):
            continue
        totals[lane] = totals.get(lane, 0) + 1
    return totals


def _sum_overdue_retention_breach_owner_target_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        owner_target = scope.get("overdue_retention_breach_owner_target")
        if not isinstance(owner_target, str):
            continue
        totals[owner_target] = totals.get(owner_target, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        mode = scope.get("overdue_retention_breach_follow_through_mode")
        if not isinstance(mode, str):
            continue
        totals[mode] = totals.get(mode, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_outcome")
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_completion_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_completion_state")
        if not isinstance(state, str):
            continue
        totals[state] = totals.get(state, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_verification_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_verification_state")
        if not isinstance(state, str):
            continue
        totals[state] = totals.get(state, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_verification_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_verification_outcome")
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals
