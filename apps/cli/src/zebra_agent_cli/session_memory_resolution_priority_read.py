from __future__ import annotations

from typing import cast

from zebra_agent_cli.session_memory_ranking import (
    _action_priority_rank,
)


def _highest_priority_overdue_trend_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        signal = scope.get("overdue_trend_signal")
        rank = scope.get("overdue_trend_rank")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("overdue_trend_reasons")
        if not (
            overdue is True
            and isinstance(signal, str)
            and isinstance(rank, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_trend_signal": signal,
            "overdue_trend_rank": rank,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_trend_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None:
            highest = candidate
            continue
        highest_rank = cast(int, highest["overdue_trend_rank"])
        highest_signal = highest["overdue_trend_signal"]
        if rank > highest_rank or (rank == highest_rank and signal < str(highest_signal)):
            highest = candidate
    return highest


def _highest_priority_overdue_intervention_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        hint = scope.get("overdue_intervention_hint")
        priority = scope.get("overdue_intervention_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_intervention_target_memory_id")
        reasons = scope.get("overdue_intervention_reasons")
        if not (
            overdue is True
            and isinstance(hint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_intervention_hint": hint,
            "overdue_intervention_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_intervention_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_intervention_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_escalation_lane_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        lane = scope.get("overdue_escalation_lane")
        priority = scope.get("overdue_escalation_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_escalation_target_memory_id")
        reasons = scope.get("overdue_escalation_reasons")
        if not (
            overdue is True
            and isinstance(lane, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_escalation_lane": lane,
            "overdue_escalation_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_escalation_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_escalation_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_recovery_path_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        path = scope.get("overdue_recovery_path")
        priority = scope.get("overdue_recovery_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_recovery_target_memory_id")
        reasons = scope.get("overdue_recovery_reasons")
        if not (
            overdue is True
            and isinstance(path, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_recovery_path": path,
            "overdue_recovery_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_recovery_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_recovery_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_resolution_checkpoint_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        checkpoint = scope.get("overdue_resolution_checkpoint")
        priority = scope.get("overdue_resolution_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_resolution_target_memory_id")
        reasons = scope.get("overdue_resolution_reasons")
        if not (
            overdue is True
            and isinstance(checkpoint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_resolution_checkpoint": checkpoint,
            "overdue_resolution_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_resolution_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_resolution_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_resolution_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        outcome = scope.get("overdue_resolution_outcome")
        priority = scope.get("overdue_resolution_outcome_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_resolution_outcome_target_memory_id")
        reasons = scope.get("overdue_resolution_outcome_reasons")
        if not (
            overdue is True
            and isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_resolution_outcome": outcome,
            "overdue_resolution_outcome_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_resolution_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_resolution_outcome_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_closure_decision_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        decision = scope.get("overdue_closure_decision")
        priority = scope.get("overdue_closure_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_closure_target_memory_id")
        reasons = scope.get("overdue_closure_reasons")
        if not (
            overdue is True
            and isinstance(decision, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_closure_decision": decision,
            "overdue_closure_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_closure_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_closure_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_archive_recommendation_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        recommendation = scope.get("overdue_archive_recommendation")
        priority = scope.get("overdue_archive_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_archive_target_memory_id")
        reasons = scope.get("overdue_archive_reasons")
        if not (
            overdue is True
            and isinstance(recommendation, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_archive_recommendation": recommendation,
            "overdue_archive_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (target_memory_id if isinstance(target_memory_id, str) else None),
            "overdue_archive_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_archive_priority"])
        ):
            highest = candidate
    return highest
