from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryVisibility
from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_inventory_review_metrics_read import (
    _read_memory_backlog_aging_signals,
    _read_memory_backlog_pressure_signals,
    _read_memory_governance_signals,
    _read_memory_inventory,
    _read_memory_queue_summary,
    _read_memory_review_velocity_signals,
)
from zebra_agent_api.memory_pressure_pipeline_read import (
    _read_memory_escalation_follow_up_windows,
    _read_memory_follow_up_overdue_flags,
    _read_memory_pressure_action_hints,
    _read_memory_pressure_escalation_recommendations,
)

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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        stores=stores,
        query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_INVENTORY_STATUSES,
        ),
    )


def read_repo_memory_queue(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
) -> list[dict[str, object]]:
    return _read_memory_inventory(
        database_path=database_path,
        stores=stores,
        query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_repo_memory_queue_summary(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
) -> dict[str, object]:
    return _read_memory_queue_summary(
        database_path=database_path,
        stores=stores,
        query=MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=_QUEUE_STATUSES,
        ),
    )


def read_repo_memory_governance_signals(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
) -> dict[str, object]:
    return _read_memory_governance_signals(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_aging_signals(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_review_velocity_signals(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_backlog_pressure_signals(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_action_hints(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_pressure_escalation_recommendations(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_escalation_follow_up_windows(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_follow_up_overdue_flags(
        database_path=database_path,
        stores=stores,
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
