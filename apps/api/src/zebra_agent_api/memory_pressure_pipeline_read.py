from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.memories import MemoryQuery

from zebra_agent_api.memory_inventory_review_metrics_read import (
    _read_memory_backlog_pressure_signals,
)
from zebra_agent_api.memory_pressure_classification_read import (
    _classify_action_hint,
    _classify_escalation_recommendation,
    _classify_follow_up_overdue_flag,
    _classify_follow_up_window,
)


def _read_memory_pressure_action_hints(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    pressure = _read_memory_backlog_pressure_signals(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    action = _classify_action_hint(pressure)
    return {
        **pressure,
        "action_hint": action["hint"],
        "action_priority": action["priority"],
        "action_target_memory_id": action["target_memory_id"],
        "action_reasons": action["reasons"],
    }


def _read_memory_pressure_escalation_recommendations(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    action_view = _read_memory_pressure_action_hints(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    escalation = _classify_escalation_recommendation(action_view)
    return {
        **action_view,
        "escalation_recommendation": escalation["recommendation"],
        "escalation_priority": escalation["priority"],
        "escalation_target_memory_id": escalation["target_memory_id"],
        "escalation_reasons": escalation["reasons"],
    }


def _read_memory_escalation_follow_up_windows(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    escalation_view = _read_memory_pressure_escalation_recommendations(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    follow_up = _classify_follow_up_window(escalation_view, as_of=as_of.astimezone(UTC))
    return {
        **escalation_view,
        "follow_up_window": follow_up["window"],
        "follow_up_priority": follow_up["priority"],
        "follow_up_due_at": follow_up["due_at"],
        "follow_up_target_memory_id": follow_up["target_memory_id"],
        "follow_up_reasons": follow_up["reasons"],
    }


def _read_memory_follow_up_overdue_flags(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    follow_up_view = _read_memory_escalation_follow_up_windows(
        database_path=database_path,
        queue_query=queue_query,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    overdue = _classify_follow_up_overdue_flag(follow_up_view, as_of=as_of.astimezone(UTC))
    return {
        **follow_up_view,
        "follow_up_overdue": overdue["overdue"],
        "follow_up_overdue_priority": overdue["priority"],
        "follow_up_overdue_since": overdue["overdue_since"],
        "follow_up_overdue_target_memory_id": overdue["target_memory_id"],
        "follow_up_overdue_reasons": overdue["reasons"],
    }
