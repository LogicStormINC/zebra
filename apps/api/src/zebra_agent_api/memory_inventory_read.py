from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.application import serialize_scoped_memory_inventory
from agent_core.domain.memories import MemoryQuery, MemoryRecord, MemoryStatus, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore

_INVENTORY_STATUSES = (
    MemoryStatus.CANDIDATE,
    MemoryStatus.CONFIRMED,
    MemoryStatus.SUPERSEDED,
    MemoryStatus.EXPIRED,
)
_QUEUE_STATUSES = (MemoryStatus.CANDIDATE,)


def read_repo_memory_inventory(
    *,
    database_path: Path,
    repo_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
    )


def read_repo_memory_queue(
    *,
    database_path: Path,
    repo_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_repo_memory_queue_summary(
    *,
    database_path: Path,
    repo_id: str,
) -> dict[str, object]:
    return _read_memory_queue_summary(
        database_path=database_path,
        query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_repo_memory_governance_signals(
    *,
    database_path: Path,
    repo_id: str,
) -> dict[str, object]:
    return _read_memory_governance_signals(
        database_path=database_path,
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_repo_memory_backlog_aging_signals(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_aging_signals(
        database_path=database_path,
        query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_review_velocity_signals(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_review_velocity_signals(
        database_path=database_path,
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_backlog_pressure_signals(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_pressure_signals(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_pressure_action_hints(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_action_hints(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_pressure_escalation_recommendations(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_escalation_recommendations(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_escalation_follow_up_windows(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_escalation_follow_up_windows(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_follow_up_overdue_flags(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_follow_up_overdue_flags(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_age_buckets(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_age_buckets(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_type_rollups(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_type_rollups(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_visibility_rollups(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_visibility_rollups(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_trend_signals(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_trend_signals(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_intervention_hints(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_intervention_hints(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_escalation_lanes(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_escalation_lanes(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_recovery_paths(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_recovery_paths(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_resolution_checkpoints(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_checkpoints(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_resolution_outcomes(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_closure_decisions(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_closure_decisions(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_archive_recommendations(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_archive_recommendations(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_guidance(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_guidance(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_windows(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_windows(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breaches(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breaches(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_aging(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_aging(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_actions(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_actions(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_lanes(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_lanes(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_owner_targets(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_owner_targets(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_follow_through_modes(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_modes(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_follow_through_outcomes(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_follow_through_completion_states(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_completion_states(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_follow_through_verification_states(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_states(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes(
    *,
    database_path: Path,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_inventory(
    *,
    database_path: Path,
    user_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
    )


def read_user_memory_queue(
    *,
    database_path: Path,
    user_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_user_memory_queue_summary(
    *,
    database_path: Path,
    user_id: str,
) -> dict[str, object]:
    return _read_memory_queue_summary(
        database_path=database_path,
        query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_user_memory_governance_signals(
    *,
    database_path: Path,
    user_id: str,
) -> dict[str, object]:
    return _read_memory_governance_signals(
        database_path=database_path,
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_user_memory_backlog_aging_signals(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_aging_signals(
        database_path=database_path,
        query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_review_velocity_signals(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_review_velocity_signals(
        database_path=database_path,
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_backlog_pressure_signals(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_pressure_signals(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_pressure_action_hints(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_action_hints(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_pressure_escalation_recommendations(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_escalation_recommendations(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_escalation_follow_up_windows(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_escalation_follow_up_windows(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_follow_up_overdue_flags(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_follow_up_overdue_flags(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_age_buckets(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_age_buckets(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_type_rollups(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_type_rollups(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_visibility_rollups(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_visibility_rollups(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_trend_signals(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_trend_signals(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_intervention_hints(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_intervention_hints(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_escalation_lanes(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_escalation_lanes(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_recovery_paths(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_recovery_paths(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_resolution_checkpoints(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_checkpoints(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_resolution_outcomes(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_closure_decisions(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_closure_decisions(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_archive_recommendations(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_archive_recommendations(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_guidance(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_guidance(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_windows(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_windows(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breaches(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breaches(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_aging(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_aging(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_actions(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_actions(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_lanes(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_lanes(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_owner_targets(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_owner_targets(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_follow_through_modes(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_modes(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_follow_through_outcomes(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_follow_through_completion_states(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_completion_states(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_follow_through_verification_states(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_states(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_user_memory_overdue_retention_breach_follow_through_verification_outcomes(
    *,
    database_path: Path,
    user_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            user_id=user_id,
            visibility=MemoryVisibility.USER,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_inventory(
    *,
    database_path: Path,
    tenant_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
    )


def read_tenant_memory_queue(
    *,
    database_path: Path,
    tenant_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_tenant_memory_queue_summary(
    *,
    database_path: Path,
    tenant_id: str,
) -> dict[str, object]:
    return _read_memory_queue_summary(
        database_path=database_path,
        query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_tenant_memory_governance_signals(
    *,
    database_path: Path,
    tenant_id: str,
) -> dict[str, object]:
    return _read_memory_governance_signals(
        database_path=database_path,
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_tenant_memory_backlog_aging_signals(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_aging_signals(
        database_path=database_path,
        query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_review_velocity_signals(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_review_velocity_signals(
        database_path=database_path,
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_backlog_pressure_signals(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_pressure_signals(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_pressure_action_hints(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_action_hints(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_pressure_escalation_recommendations(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_escalation_recommendations(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_escalation_follow_up_windows(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_escalation_follow_up_windows(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_follow_up_overdue_flags(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_follow_up_overdue_flags(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_age_buckets(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_age_buckets(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_type_rollups(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_type_rollups(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_visibility_rollups(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_visibility_rollups(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_trend_signals(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_trend_signals(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_intervention_hints(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_intervention_hints(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_escalation_lanes(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_escalation_lanes(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_recovery_paths(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_recovery_paths(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_resolution_checkpoints(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_checkpoints(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_resolution_outcomes(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_closure_decisions(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_closure_decisions(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_archive_recommendations(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_archive_recommendations(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_guidance(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_guidance(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_windows(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_windows(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breaches(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breaches(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_aging(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_aging(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_actions(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_actions(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_lanes(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_lanes(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_owner_targets(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_owner_targets(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_follow_through_modes(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_modes(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_follow_through_outcomes(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_follow_through_completion_states(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_completion_states(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_follow_through_verification_states(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_states(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def read_tenant_memory_overdue_retention_breach_follow_through_verification_outcomes(
    *,
    database_path: Path,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_outcomes(
        database_path=database_path,
        queue_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_QUEUE_STATUSES,
        ),
        inventory_query=MemoryQuery(
            tenant_id=tenant_id,
            visibility=MemoryVisibility.TENANT,
            statuses=_INVENTORY_STATUSES,
        ),
        as_of=as_of,
    )


def _read_memory_inventory(
    *,
    database_path: Path,
    query: MemoryQuery,
) -> list[dict[str, object]]:
    event_store = SQLiteEventStore(database_path)
    records = SQLiteMemoryStore(database_path).list(query)
    return serialize_scoped_memory_inventory(records, event_store.list_for_session)


def _read_memory_queue_summary(
    *,
    database_path: Path,
    query: MemoryQuery,
) -> dict[str, object]:
    records = SQLiteMemoryStore(database_path).list(query)
    latest_record = _latest_record(records)
    return {
        "pending_count": len(records),
        "queue_status": "pending" if records else "empty",
        "latest_memory_id": None if latest_record is None else str(latest_record.memory_id),
        "latest_updated_at": (
            None if latest_record is None else latest_record.updated_at.isoformat()
        ),
    }


def _read_memory_backlog_aging_signals(
    *,
    database_path: Path,
    query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    records = SQLiteMemoryStore(database_path).list(query)
    oldest_record = _oldest_record(records)
    normalized_as_of = as_of.astimezone(UTC)
    return {
        **_read_memory_queue_summary(
            database_path=database_path,
            query=query,
        ),
        "reference_at": normalized_as_of.isoformat(),
        "pending_age_buckets": _count_pending_age_buckets(records, normalized_as_of),
        "oldest_pending_memory_id": (
            None if oldest_record is None else str(oldest_record.memory_id)
        ),
        "oldest_pending_captured_at": (
            None if oldest_record is None else oldest_record.created_at.isoformat()
        ),
        "oldest_pending_age_seconds": (
            None
            if oldest_record is None
            else _age_seconds(oldest_record.created_at, normalized_as_of)
        ),
        "oldest_pending_age_days": (
            None
            if oldest_record is None
            else _age_seconds(oldest_record.created_at, normalized_as_of) // 86_400
        ),
    }


def _read_memory_review_velocity_signals(
    *,
    database_path: Path,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    inventory_rows = _read_memory_inventory(
        database_path=database_path,
        query=inventory_query,
    )
    normalized_as_of = as_of.astimezone(UTC)
    latest_review = _latest_review(inventory_rows)
    return {
        "reference_at": normalized_as_of.isoformat(),
        "reviewed_count": _reviewed_count(inventory_rows),
        "reviewed_last_24h_count": _count_recent_reviews(
            inventory_rows,
            as_of=normalized_as_of,
            seconds=86_400,
        ),
        "reviewed_last_7d_count": _count_recent_reviews(
            inventory_rows,
            as_of=normalized_as_of,
            seconds=604_800,
        ),
        "reviewed_last_30d_count": _count_recent_reviews(
            inventory_rows,
            as_of=normalized_as_of,
            seconds=2_592_000,
        ),
        "latest_reviewed_at": (
            None if latest_review is None else latest_review["recorded_at"]
        ),
        "latest_review_status": None if latest_review is None else latest_review["status"],
        "latest_review_operator": (
            None if latest_review is None else latest_review["operator"]
        ),
        "latest_review_window": (
            None
            if latest_review is None
            else _review_window_label(latest_review["recorded_at"], normalized_as_of)
        ),
    }


def _read_memory_backlog_pressure_signals(
    *,
    database_path: Path,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    aging = _read_memory_backlog_aging_signals(
        database_path=database_path,
        query=queue_query,
        as_of=as_of,
    )
    velocity = _read_memory_review_velocity_signals(
        database_path=database_path,
        inventory_query=inventory_query,
        as_of=as_of,
    )
    pressure = _classify_pressure(aging=aging, velocity=velocity)
    return {
        **aging,
        **velocity,
        "pressure_level": pressure["level"],
        "pressure_reasons": pressure["reasons"],
    }


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
        _count_memory_types(queue_rows)
        if overdue_view.get("follow_up_overdue") is True
        else {}
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
        "overdue_retention_breach_follow_through_outcome_memory_id": (
            outcome["target_memory_id"]
        ),
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
    completion = _classify_overdue_retention_breach_follow_through_completion_state(
        overdue_view
    )
    return {
        **overdue_view,
        "overdue_retention_breach_follow_through_completion_state": completion["state"],
        "overdue_retention_breach_follow_through_completion_priority": completion[
            "priority"
        ],
        "overdue_retention_breach_follow_through_completion_memory_id": completion[
            "target_memory_id"
        ],
        "overdue_retention_breach_follow_through_completion_reasons": completion[
            "reasons"
        ],
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
        "overdue_retention_breach_follow_through_verification_state": verification[
            "state"
        ],
        "overdue_retention_breach_follow_through_verification_priority": verification[
            "priority"
        ],
        "overdue_retention_breach_follow_through_verification_memory_id": verification[
            "target_memory_id"
        ],
        "overdue_retention_breach_follow_through_verification_reasons": verification[
            "reasons"
        ],
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
    outcome = _classify_overdue_retention_breach_follow_through_verification_outcome(
        overdue_view
    )
    return {
        **overdue_view,
        "overdue_retention_breach_follow_through_verification_outcome": outcome[
            "outcome"
        ],
        "overdue_retention_breach_follow_through_verification_outcome_priority": outcome[
            "priority"
        ],
        "overdue_retention_breach_follow_through_verification_outcome_memory_id": (
            outcome["target_memory_id"]
        ),
        "overdue_retention_breach_follow_through_verification_outcome_reasons": outcome[
            "reasons"
        ],
    }


def _latest_record(records: list[MemoryRecord]) -> MemoryRecord | None:
    if not records:
        return None
    return max(records, key=lambda record: (record.updated_at, str(record.memory_id)))


def _read_memory_governance_signals(
    *,
    database_path: Path,
    inventory_query: MemoryQuery,
    queue_query: MemoryQuery,
) -> dict[str, object]:
    inventory_rows = _read_memory_inventory(
        database_path=database_path,
        query=inventory_query,
    )
    queue_rows = _read_memory_inventory(
        database_path=database_path,
        query=queue_query,
    )
    queue_summary = _read_memory_queue_summary(
        database_path=database_path,
        query=queue_query,
    )
    latest_review = _latest_review(inventory_rows)
    return {
        **queue_summary,
        "pending_by_type": _count_memory_types(queue_rows),
        "reviewed_count": _reviewed_count(inventory_rows),
        "review_status_counts": _count_review_statuses(inventory_rows),
        "latest_reviewed_at": (
            None if latest_review is None else latest_review["recorded_at"]
        ),
        "latest_review_status": None if latest_review is None else latest_review["status"],
        "latest_review_operator": (
            None if latest_review is None else latest_review["operator"]
        ),
    }


def _count_memory_types(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        memory_type = row.get("memory_type")
        if not isinstance(memory_type, str):
            continue
        counts[memory_type] = counts.get(memory_type, 0) + 1
    return counts


def _count_memory_visibilities(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        visibility = row.get("visibility")
        if not isinstance(visibility, str):
            continue
        counts[visibility] = counts.get(visibility, 0) + 1
    return counts


def _highest_count_entry(counts: dict[str, int]) -> tuple[str | None, int]:
    highest_name: str | None = None
    highest_count = 0
    for name in sorted(counts):
        count = counts[name]
        if count > highest_count:
            highest_name = name
            highest_count = count
    return highest_name, highest_count


def _field_for_memory_id(
    rows: list[dict[str, object]],
    memory_id: object,
    *,
    field_name: str,
) -> str | None:
    if not isinstance(memory_id, str):
        return None
    for row in rows:
        if row.get("memory_id") != memory_id:
            continue
        value = row.get(field_name)
        if isinstance(value, str):
            return value
    return None


def _reviewed_count(rows: list[dict[str, object]]) -> int:
    total = 0
    for row in rows:
        if isinstance(row.get("last_review"), dict):
            total += 1
    return total


def _count_review_statuses(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        last_review = row.get("last_review")
        if not isinstance(last_review, dict):
            continue
        status = last_review.get("status")
        if not isinstance(status, str):
            continue
        counts[status] = counts.get(status, 0) + 1
    return counts


def _latest_review(rows: list[dict[str, object]]) -> dict[str, str] | None:
    latest: dict[str, str] | None = None
    for row in rows:
        last_review = row.get("last_review")
        if not isinstance(last_review, dict):
            continue
        recorded_at = last_review.get("recorded_at")
        status = last_review.get("status")
        operator = last_review.get("operator")
        if not (
            isinstance(recorded_at, str)
            and isinstance(status, str)
            and isinstance(operator, str)
        ):
            continue
        candidate = {
            "recorded_at": recorded_at,
            "status": status,
            "operator": operator,
        }
        if latest is None or candidate["recorded_at"] > latest["recorded_at"]:
            latest = candidate
    return latest


def _count_recent_reviews(
    rows: list[dict[str, object]],
    *,
    as_of: datetime,
    seconds: int,
) -> int:
    total = 0
    for row in rows:
        last_review = row.get("last_review")
        if not isinstance(last_review, dict):
            continue
        recorded_at = last_review.get("recorded_at")
        if not isinstance(recorded_at, str):
            continue
        if _reviewed_within_window(recorded_at, as_of=as_of, seconds=seconds):
            total += 1
    return total


def _oldest_record(records: list[MemoryRecord]) -> MemoryRecord | None:
    if not records:
        return None
    return min(records, key=lambda record: (record.created_at, str(record.memory_id)))


def _count_pending_age_buckets(
    records: list[MemoryRecord],
    as_of: datetime,
) -> dict[str, int]:
    buckets = {
        "lt_1d": 0,
        "gte_1d_lt_3d": 0,
        "gte_3d_lt_7d": 0,
        "gte_7d": 0,
    }
    for record in records:
        age_seconds = _age_seconds(record.created_at, as_of)
        if age_seconds < 86_400:
            buckets["lt_1d"] += 1
        elif age_seconds < 259_200:
            buckets["gte_1d_lt_3d"] += 1
        elif age_seconds < 604_800:
            buckets["gte_3d_lt_7d"] += 1
        else:
            buckets["gte_7d"] += 1
    return buckets


def _age_seconds(created_at: datetime, as_of: datetime) -> int:
    return max(0, int((as_of - created_at.astimezone(UTC)).total_seconds()))


def _reviewed_within_window(
    recorded_at: str,
    *,
    as_of: datetime,
    seconds: int,
) -> bool:
    try:
        recorded = datetime.fromisoformat(recorded_at).astimezone(UTC)
    except ValueError:
        return False
    return _age_seconds(recorded, as_of) <= seconds


def _review_window_label(recorded_at: str, as_of: datetime) -> str:
    if _reviewed_within_window(recorded_at, as_of=as_of, seconds=86_400):
        return "last_24h"
    if _reviewed_within_window(recorded_at, as_of=as_of, seconds=604_800):
        return "last_7d"
    if _reviewed_within_window(recorded_at, as_of=as_of, seconds=2_592_000):
        return "last_30d"
    return "older"


def _classify_pressure(
    *,
    aging: dict[str, object],
    velocity: dict[str, object],
) -> dict[str, object]:
    pending_count = _int_field(aging, "pending_count")
    oldest_pending_age_days = _int_field(aging, "oldest_pending_age_days")
    reviewed_last_24h_count = _int_field(velocity, "reviewed_last_24h_count")
    reviewed_last_7d_count = _int_field(velocity, "reviewed_last_7d_count")

    if pending_count == 0:
        return {
            "level": "clear",
            "reasons": ["no_pending_backlog"],
        }

    reasons: list[str] = []
    if oldest_pending_age_days >= 7:
        reasons.append("stale_backlog")
    elif oldest_pending_age_days >= 3:
        reasons.append("aging_backlog")

    if pending_count >= 5:
        reasons.append("large_backlog")
    elif pending_count >= 3:
        reasons.append("growing_backlog")

    if reviewed_last_7d_count == 0:
        reasons.append("no_recent_reviews")
    elif reviewed_last_24h_count == 0:
        reasons.append("no_reviews_last_24h")

    if "stale_backlog" in reasons or (
        "large_backlog" in reasons and "no_recent_reviews" in reasons
    ):
        return {"level": "high", "reasons": reasons}
    if reasons:
        return {"level": "elevated", "reasons": reasons}
    return {"level": "steady", "reasons": ["active_backlog"]}


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
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "reasons": pressure_reasons or ["stalled_high_pressure"],
        }
    if level == "high":
        return {
            "recommendation": "schedule_same_day_review_burst",
            "priority": "medium",
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "reasons": pressure_reasons or ["high_pressure_requires_review_burst"],
        }
    if action_hint == "restart_review_queue" and reviewed_last_24h_count == 0:
        return {
            "recommendation": "monitor_until_next_review_window",
            "priority": "low",
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
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
    normalized_age_days = (
        oldest_pending_age_days if isinstance(oldest_pending_age_days, int) else 0
    )
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
    priority = str(
        overdue_view.get("overdue_retention_breach_follow_through_priority") or "none"
    )
    target_memory_id = overdue_view.get(
        "overdue_retention_breach_follow_through_memory_id"
    )
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
    outcome = str(
        overdue_view.get("overdue_retention_breach_follow_through_outcome") or ""
    )
    priority = str(
        overdue_view.get("overdue_retention_breach_follow_through_outcome_priority")
        or "none"
    )
    target_memory_id = overdue_view.get(
        "overdue_retention_breach_follow_through_outcome_memory_id"
    )
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


def _classify_overdue_retention_breach_follow_through_verification_state(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    completion_state = str(
        overdue_view.get("overdue_retention_breach_follow_through_completion_state")
        or ""
    )
    priority = str(
        overdue_view.get("overdue_retention_breach_follow_through_completion_priority")
        or "none"
    )
    target_memory_id = overdue_view.get(
        "overdue_retention_breach_follow_through_completion_memory_id"
    )
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "state": "verification_not_required",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if completion_state == "operator_completion_pending":
        return {
            "state": "operator_verification_pending",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["operator_completion_requires_verification_before_signoff"],
        }
    if completion_state == "owner_completion_pending":
        return {
            "state": "owner_verification_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["owner_completion_requires_verification_before_signoff"],
        }
    if completion_state == "manager_completion_pending":
        return {
            "state": "manager_verification_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["manager_completion_requires_verification_before_signoff"],
        }
    if completion_state == "admin_override_completion_pending":
        return {
            "state": "admin_override_verification_pending",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["admin_override_completion_requires_verification_before_signoff"],
        }
    return {
        "state": "verification_monitoring_only",
        "priority": "low" if priority != "none" else "none",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_follow_through_verification_monitoring"],
    }


def _classify_overdue_retention_breach_follow_through_verification_outcome(
    overdue_view: dict[str, object],
) -> dict[str, object]:
    state = str(
        overdue_view.get("overdue_retention_breach_follow_through_verification_state")
        or ""
    )
    priority = str(
        overdue_view.get("overdue_retention_breach_follow_through_verification_priority")
        or "none"
    )
    target_memory_id = overdue_view.get(
        "overdue_retention_breach_follow_through_verification_memory_id"
    )
    normalized_target = target_memory_id if isinstance(target_memory_id, str) else None

    if overdue_view.get("follow_up_overdue") is not True:
        return {
            "outcome": "verification_resolved",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["scope_not_overdue"],
        }
    if state == "admin_override_verification_pending":
        return {
            "outcome": "awaiting_admin_override_verification_outcome",
            "priority": "high",
            "target_memory_id": normalized_target,
            "reasons": ["admin_override_verification_pending_requires_explicit_outcome"],
        }
    if state == "manager_verification_pending":
        return {
            "outcome": "awaiting_manager_verification_outcome",
            "priority": "high" if priority == "high" else "medium",
            "target_memory_id": normalized_target,
            "reasons": ["manager_verification_pending_requires_explicit_outcome"],
        }
    if state == "owner_verification_pending":
        return {
            "outcome": "awaiting_owner_verification_outcome",
            "priority": "medium",
            "target_memory_id": normalized_target,
            "reasons": ["owner_verification_pending_requires_explicit_outcome"],
        }
    if state == "operator_verification_pending":
        return {
            "outcome": "awaiting_operator_verification_outcome",
            "priority": "medium" if priority == "medium" else "low",
            "target_memory_id": normalized_target,
            "reasons": ["operator_verification_pending_requires_explicit_outcome"],
        }
    if state == "verification_not_required":
        return {
            "outcome": "verification_resolved",
            "priority": "none",
            "target_memory_id": None,
            "reasons": ["verification_not_required"],
        }
    return {
        "outcome": "verification_monitoring_only",
        "priority": "low" if priority != "none" else "none",
        "target_memory_id": normalized_target,
        "reasons": ["fallback_verification_outcome_monitoring"],
    }


def _int_field(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0
