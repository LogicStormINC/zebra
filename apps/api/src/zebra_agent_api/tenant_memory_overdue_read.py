from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryVisibility
from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_overdue_pipeline_read import (
    _read_memory_overdue_age_buckets,
    _read_memory_overdue_closure_decisions,
    _read_memory_overdue_escalation_lanes,
    _read_memory_overdue_intervention_hints,
    _read_memory_overdue_recovery_paths,
    _read_memory_overdue_resolution_checkpoints,
    _read_memory_overdue_resolution_outcomes,
    _read_memory_overdue_trend_signals,
    _read_memory_overdue_type_rollups,
    _read_memory_overdue_visibility_rollups,
)
from zebra_agent_api.memory_retention_pipeline_read import (
    _read_memory_overdue_archive_recommendations,
)

_INVENTORY_STATUSES = (
    MemoryStatus.CANDIDATE,
    MemoryStatus.CONFIRMED,
    MemoryStatus.SUPERSEDED,
    MemoryStatus.EXPIRED,
)

_QUEUE_STATUSES = (MemoryStatus.CANDIDATE,)


def read_tenant_memory_overdue_age_buckets(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_age_buckets(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_type_rollups(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_visibility_rollups(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_trend_signals(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_intervention_hints(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_escalation_lanes(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_recovery_paths(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_checkpoints(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_resolution_outcomes(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_closure_decisions(
        database_path=database_path,
        stores=stores,
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
    stores: ControlPlaneStores | None = None,
    tenant_id: str,
    as_of: datetime,
) -> dict[str, object]:
    return _read_memory_overdue_archive_recommendations(
        database_path=database_path,
        stores=stores,
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
