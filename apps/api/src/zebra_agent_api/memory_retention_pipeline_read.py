from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_core.domain.memories import MemoryQuery

from zebra_agent_api.memory_breach_classification_read import (
    _classify_overdue_retention_breach_action,
    _classify_overdue_retention_breach_follow_through_completion_state,
    _classify_overdue_retention_breach_follow_through_mode,
    _classify_overdue_retention_breach_follow_through_outcome,
    _classify_overdue_retention_breach_lane,
    _classify_overdue_retention_breach_owner_target,
)
from zebra_agent_api.memory_follow_through_classification_read import (
    _classify_overdue_retention_breach_follow_through_verification_outcome,
    _classify_overdue_retention_breach_follow_through_verification_state,
)
from zebra_agent_api.memory_overdue_pipeline_read import (
    _read_memory_overdue_closure_decisions,
)
from zebra_agent_api.memory_retention_classification_read import (
    _classify_overdue_archive_recommendation,
    _classify_overdue_retention_breach,
    _classify_overdue_retention_breach_aging,
    _classify_overdue_retention_guidance,
    _classify_overdue_retention_window,
)


def _read_memory_overdue_archive_recommendations(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_closure_decisions(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    recommendation = _classify_overdue_archive_recommendation(overdue_view)
    return {
        **overdue_view,
        "overdue_archive_recommendation": recommendation["recommendation"],
        "overdue_archive_priority": recommendation["priority"],
        "overdue_archive_target_memory_id": recommendation["target_memory_id"],
        "overdue_archive_reasons": recommendation["reasons"],
    }


def _read_memory_overdue_retention_guidance(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_archive_recommendations(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    guidance = _classify_overdue_retention_guidance(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_guidance": guidance["guidance"],
        "overdue_retention_priority": guidance["priority"],
        "overdue_retention_bucket": guidance["bucket"],
        "overdue_retention_target_memory_id": guidance["target_memory_id"],
        "overdue_retention_reasons": guidance["reasons"],
    }


def _read_memory_overdue_retention_windows(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_guidance(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    window = _classify_overdue_retention_window(overdue_view=overdue_view, as_of=as_of)
    return {
        **overdue_view,
        "overdue_retention_window": window["window"],
        "overdue_retention_window_priority": window["priority"],
        "overdue_retention_window_due_at": window["due_at"],
        "overdue_retention_window_target_memory_id": window["target_memory_id"],
        "overdue_retention_window_reasons": window["reasons"],
    }


def _read_memory_overdue_retention_breaches(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_windows(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    breach = _classify_overdue_retention_breach(overdue_view=overdue_view, as_of=as_of)
    return {
        **overdue_view,
        "overdue_retention_breach": breach["breach"],
        "overdue_retention_breach_priority": breach["priority"],
        "overdue_retention_breach_due_at": breach["due_at"],
        "overdue_retention_breach_target_memory_id": breach["target_memory_id"],
        "overdue_retention_breach_reasons": breach["reasons"],
    }


def _read_memory_overdue_retention_breach_aging(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breaches(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    aging = _classify_overdue_retention_breach_aging(overdue_view=overdue_view, as_of=as_of)
    return {
        **overdue_view,
        "overdue_retention_breach_age_bucket": aging["bucket"],
        "overdue_retention_breach_age_seconds": aging["age_seconds"],
        "overdue_retention_breach_age_days": aging["age_days"],
        "overdue_retention_breach_age_reasons": aging["reasons"],
    }


def _read_memory_overdue_retention_breach_actions(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_aging(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    action = _classify_overdue_retention_breach_action(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_breach_action": action["action"],
        "overdue_retention_breach_action_priority": action["priority"],
        "overdue_retention_breach_action_target_memory_id": action["target_memory_id"],
        "overdue_retention_breach_action_reasons": action["reasons"],
    }


def _read_memory_overdue_retention_breach_lanes(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_actions(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    lane = _classify_overdue_retention_breach_lane(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_breach_lane": lane["lane"],
        "overdue_retention_breach_lane_priority": lane["priority"],
        "overdue_retention_breach_lane_target_memory_id": lane["target_memory_id"],
        "overdue_retention_breach_lane_reasons": lane["reasons"],
    }


def _read_memory_overdue_retention_breach_owner_targets(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_lanes(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    owner_target = _classify_overdue_retention_breach_owner_target(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_breach_owner_target": owner_target["owner_target"],
        "overdue_retention_breach_owner_target_priority": owner_target["priority"],
        "overdue_retention_breach_owner_target_memory_id": owner_target["target_memory_id"],
        "overdue_retention_breach_owner_target_reasons": owner_target["reasons"],
    }


def _read_memory_overdue_retention_breach_follow_through_modes(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_owner_targets(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    follow_through = _classify_overdue_retention_breach_follow_through_mode(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_breach_follow_through_mode": follow_through["mode"],
        "overdue_retention_breach_follow_through_priority": follow_through["priority"],
        "overdue_retention_breach_follow_through_memory_id": follow_through["target_memory_id"],
        "overdue_retention_breach_follow_through_reasons": follow_through["reasons"],
    }


def _read_memory_overdue_retention_breach_follow_through_outcomes(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_follow_through_modes(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    outcome = _classify_overdue_retention_breach_follow_through_outcome(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_breach_follow_through_outcome": outcome["outcome"],
        "overdue_retention_breach_follow_through_outcome_priority": outcome["priority"],
        "overdue_retention_breach_follow_through_outcome_memory_id": (outcome["target_memory_id"]),
        "overdue_retention_breach_follow_through_outcome_reasons": outcome["reasons"],
    }


def _read_memory_overdue_retention_breach_follow_through_completion_states(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_follow_through_outcomes(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    completion = _classify_overdue_retention_breach_follow_through_completion_state(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_breach_follow_through_completion_state": completion["state"],
        "overdue_retention_breach_follow_through_completion_priority": completion["priority"],
        "overdue_retention_breach_follow_through_completion_memory_id": completion[
            "target_memory_id"
        ],
        "overdue_retention_breach_follow_through_completion_reasons": completion["reasons"],
    }


def _read_memory_overdue_retention_breach_follow_through_verification_states(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_follow_through_completion_states(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    verification = _classify_overdue_retention_breach_follow_through_verification_state(
        overdue_view
    )
    return {
        **overdue_view,
        "overdue_retention_breach_follow_through_verification_state": verification["state"],
        "overdue_retention_breach_follow_through_verification_priority": verification["priority"],
        "overdue_retention_breach_follow_through_verification_memory_id": verification[
            "target_memory_id"
        ],
        "overdue_retention_breach_follow_through_verification_reasons": verification["reasons"],
    }


def _read_memory_overdue_retention_breach_follow_through_verification_outcomes(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_retention_breach_follow_through_verification_states(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    outcome = _classify_overdue_retention_breach_follow_through_verification_outcome(overdue_view)
    return {
        **overdue_view,
        "overdue_retention_breach_follow_through_verification_outcome": outcome["outcome"],
        "overdue_retention_breach_follow_through_verification_outcome_priority": outcome[
            "priority"
        ],
        "overdue_retention_breach_follow_through_verification_outcome_memory_id": (
            outcome["target_memory_id"]
        ),
        "overdue_retention_breach_follow_through_verification_outcome_reasons": outcome["reasons"],
    }
