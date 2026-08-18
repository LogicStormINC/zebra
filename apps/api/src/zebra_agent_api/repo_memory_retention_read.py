from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryVisibility
from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_retention_pipeline_read import (
    _read_memory_overdue_retention_breach_actions,
    _read_memory_overdue_retention_breach_aging,
    _read_memory_overdue_retention_breach_follow_through_completion_states,
    _read_memory_overdue_retention_breach_follow_through_modes,
    _read_memory_overdue_retention_breach_follow_through_outcomes,
    _read_memory_overdue_retention_breach_follow_through_verification_outcomes,
    _read_memory_overdue_retention_breach_follow_through_verification_states,
    _read_memory_overdue_retention_breach_lanes,
    _read_memory_overdue_retention_breach_owner_targets,
    _read_memory_overdue_retention_breaches,
    _read_memory_overdue_retention_guidance,
    _read_memory_overdue_retention_windows,
)

_INVENTORY_STATUSES = (
    MemoryStatus.CANDIDATE,
    MemoryStatus.CONFIRMED,
    MemoryStatus.SUPERSEDED,
    MemoryStatus.EXPIRED,
)

_QUEUE_STATUSES = (MemoryStatus.CANDIDATE,)


def read_repo_memory_overdue_retention_guidance(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_guidance(
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


def read_repo_memory_overdue_retention_windows(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_windows(
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


def read_repo_memory_overdue_retention_breaches(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breaches(
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


def read_repo_memory_overdue_retention_breach_aging(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_aging(
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


def read_repo_memory_overdue_retention_breach_actions(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_actions(
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


def read_repo_memory_overdue_retention_breach_lanes(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_lanes(
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


def read_repo_memory_overdue_retention_breach_owner_targets(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_owner_targets(
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


def read_repo_memory_overdue_retention_breach_follow_through_modes(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_modes(
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


def read_repo_memory_overdue_retention_breach_follow_through_outcomes(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_outcomes(
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


def read_repo_memory_overdue_retention_breach_follow_through_completion_states(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_completion_states(
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


def read_repo_memory_overdue_retention_breach_follow_through_verification_states(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_states(
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


def read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    repo_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_retention_breach_follow_through_verification_outcomes(
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
