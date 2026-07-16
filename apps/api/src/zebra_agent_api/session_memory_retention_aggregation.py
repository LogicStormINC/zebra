from __future__ import annotations


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
