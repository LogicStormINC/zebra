from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.memories import MemoryQuery

from zebra_agent_api.memory_inventory_review_metrics_read import (
    _count_memory_types,
    _count_memory_visibilities,
    _field_for_memory_id,
    _highest_count_entry,
    _read_memory_inventory,
)
from zebra_agent_api.memory_overdue_classification_read import (
    _classify_overdue_closure_decision,
    _classify_overdue_escalation_lane,
    _classify_overdue_intervention_hint,
    _classify_overdue_recovery_path,
    _classify_overdue_resolution_checkpoint,
    _classify_overdue_resolution_outcome,
)
from zebra_agent_api.memory_pressure_classification_read import (
    _classify_overdue_age_bucket,
    _classify_overdue_trend_signal,
)
from zebra_agent_api.memory_pressure_pipeline_read import (
    _read_memory_follow_up_overdue_flags,
)


def _read_memory_overdue_age_buckets(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_follow_up_overdue_flags(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    overdue_age = _classify_overdue_age_bucket(overdue_view, as_of=as_of.astimezone(UTC))
    return {
        **overdue_view,
        "overdue_age_bucket": overdue_age["bucket"],
        "overdue_age_seconds": overdue_age["age_seconds"],
        "overdue_age_days": overdue_age["age_days"],
        "overdue_age_reasons": overdue_age["reasons"],
    }


def _read_memory_overdue_type_rollups(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_age_buckets(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    queue_rows = _read_memory_inventory(
        database_path=database_path,
        query=queue_query,
    )
    overdue_counts = (
        _count_memory_types(queue_rows) if overdue_view.get("follow_up_overdue") is True else {}
    )
    highest_overdue_type, highest_overdue_count = _highest_count_entry(overdue_counts)
    target_memory_type = _field_for_memory_id(
        queue_rows,
        overdue_view.get("follow_up_overdue_target_memory_id"),
        field_name="memory_type",
    )
    return {
        **overdue_view,
        "overdue_memory_count": sum(overdue_counts.values()),
        "overdue_memory_type_counts": overdue_counts,
        "highest_overdue_memory_type": highest_overdue_type,
        "highest_overdue_memory_type_count": highest_overdue_count,
        "overdue_target_memory_type": target_memory_type,
        "overdue_type_rollup_reasons": (
            ["scope_not_overdue"]
            if overdue_view.get("follow_up_overdue") is not True
            else ["overdue_queue_type_rollup_ready"]
        ),
    }


def _read_memory_overdue_visibility_rollups(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_age_buckets(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    queue_rows = _read_memory_inventory(
        database_path=database_path,
        query=queue_query,
    )
    overdue_counts = (
        _count_memory_visibilities(queue_rows)
        if overdue_view.get("follow_up_overdue") is True
        else {}
    )
    highest_visibility, highest_visibility_count = _highest_count_entry(overdue_counts)
    target_memory_visibility = _field_for_memory_id(
        queue_rows,
        overdue_view.get("follow_up_overdue_target_memory_id"),
        field_name="visibility",
    )
    return {
        **overdue_view,
        "overdue_memory_visibility_counts": overdue_counts,
        "highest_overdue_memory_visibility": highest_visibility,
        "highest_overdue_memory_visibility_count": highest_visibility_count,
        "overdue_target_memory_visibility": target_memory_visibility,
        "overdue_visibility_rollup_reasons": (
            ["scope_not_overdue"]
            if overdue_view.get("follow_up_overdue") is not True
            else ["overdue_queue_visibility_rollup_ready"]
        ),
    }


def _read_memory_overdue_trend_signals(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_age_buckets(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    trend = _classify_overdue_trend_signal(overdue_view)
    return {
        **overdue_view,
        "overdue_trend_signal": trend["signal"],
        "overdue_trend_rank": trend["rank"],
        "overdue_trend_reasons": trend["reasons"],
    }


def _read_memory_overdue_intervention_hints(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_trend_signals(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    intervention = _classify_overdue_intervention_hint(overdue_view)
    return {
        **overdue_view,
        "overdue_intervention_hint": intervention["hint"],
        "overdue_intervention_priority": intervention["priority"],
        "overdue_intervention_target_memory_id": intervention["target_memory_id"],
        "overdue_intervention_reasons": intervention["reasons"],
    }


def _read_memory_overdue_escalation_lanes(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_intervention_hints(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    lane = _classify_overdue_escalation_lane(overdue_view)
    return {
        **overdue_view,
        "overdue_escalation_lane": lane["lane"],
        "overdue_escalation_priority": lane["priority"],
        "overdue_escalation_target_memory_id": lane["target_memory_id"],
        "overdue_escalation_reasons": lane["reasons"],
    }


def _read_memory_overdue_recovery_paths(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_escalation_lanes(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    recovery = _classify_overdue_recovery_path(overdue_view)
    return {
        **overdue_view,
        "overdue_recovery_path": recovery["path"],
        "overdue_recovery_priority": recovery["priority"],
        "overdue_recovery_target_memory_id": recovery["target_memory_id"],
        "overdue_recovery_reasons": recovery["reasons"],
    }


def _read_memory_overdue_resolution_checkpoints(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_recovery_paths(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    checkpoint = _classify_overdue_resolution_checkpoint(overdue_view)
    return {
        **overdue_view,
        "overdue_resolution_checkpoint": checkpoint["checkpoint"],
        "overdue_resolution_priority": checkpoint["priority"],
        "overdue_resolution_target_memory_id": checkpoint["target_memory_id"],
        "overdue_resolution_reasons": checkpoint["reasons"],
    }


def _read_memory_overdue_resolution_outcomes(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_resolution_checkpoints(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    outcome = _classify_overdue_resolution_outcome(overdue_view)
    return {
        **overdue_view,
        "overdue_resolution_outcome": outcome["outcome"],
        "overdue_resolution_outcome_priority": outcome["priority"],
        "overdue_resolution_outcome_target_memory_id": outcome["target_memory_id"],
        "overdue_resolution_outcome_reasons": outcome["reasons"],
    }


def _read_memory_overdue_closure_decisions(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    overdue_view = _read_memory_overdue_resolution_outcomes(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    decision = _classify_overdue_closure_decision(overdue_view)
    return {
        **overdue_view,
        "overdue_closure_decision": decision["decision"],
        "overdue_closure_priority": decision["priority"],
        "overdue_closure_target_memory_id": decision["target_memory_id"],
        "overdue_closure_reasons": decision["reasons"],
    }
