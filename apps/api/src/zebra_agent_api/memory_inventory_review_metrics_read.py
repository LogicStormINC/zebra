from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import serialize_scoped_memory_inventory
from agent_core.domain.memories import MemoryQuery, MemoryRecord
from agent_storage import (
    ControlPlaneStores,
    SQLiteMemoryStore,
    sqlite_control_plane_stores,
)

from zebra_agent_api.memory_follow_through_classification_read import (
    _int_field,
)


def _read_memory_inventory(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None,
    query: MemoryQuery,
) -> list[dict[str, object]]:
    event_store = (stores or sqlite_control_plane_stores(database_path)).events
    records = SQLiteMemoryStore(database_path).list(query)
    return serialize_scoped_memory_inventory(records, event_store.list_for_session)


def _read_memory_queue_summary(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None,
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
    stores: ControlPlaneStores | None,
    query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    records = SQLiteMemoryStore(database_path).list(query)
    oldest_record = _oldest_record(records)
    normalized_as_of = as_of.astimezone(UTC)
    return {
        **_read_memory_queue_summary(
            database_path=database_path,
            stores=stores,
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
    stores: ControlPlaneStores | None,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    inventory_rows = _read_memory_inventory(
        database_path=database_path,
        stores=stores,
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
        "latest_reviewed_at": (None if latest_review is None else latest_review["recorded_at"]),
        "latest_review_status": None if latest_review is None else latest_review["status"],
        "latest_review_operator": (None if latest_review is None else latest_review["operator"]),
        "latest_review_window": (
            None
            if latest_review is None
            else _review_window_label(latest_review["recorded_at"], normalized_as_of)
        ),
    }


def _read_memory_backlog_pressure_signals(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None,
    queue_query: MemoryQuery,
    inventory_query: MemoryQuery,
    as_of: datetime,
) -> dict[str, object]:
    aging = _read_memory_backlog_aging_signals(
        database_path=database_path,
        stores=stores,
        query=queue_query,
        as_of=as_of,
    )
    velocity = _read_memory_review_velocity_signals(
        database_path=database_path,
        stores=stores,
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


def _latest_record(records: list[MemoryRecord]) -> MemoryRecord | None:
    if not records:
        return None
    return max(records, key=lambda record: (record.updated_at, str(record.memory_id)))


def _read_memory_governance_signals(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None,
    inventory_query: MemoryQuery,
    queue_query: MemoryQuery,
) -> dict[str, object]:
    inventory_rows = _read_memory_inventory(
        database_path=database_path,
        stores=stores,
        query=inventory_query,
    )
    queue_rows = _read_memory_inventory(
        database_path=database_path,
        stores=stores,
        query=queue_query,
    )
    queue_summary = _read_memory_queue_summary(
        database_path=database_path,
        stores=stores,
        query=queue_query,
    )
    latest_review = _latest_review(inventory_rows)
    return {
        **queue_summary,
        "pending_by_type": _count_memory_types(queue_rows),
        "reviewed_count": _reviewed_count(inventory_rows),
        "review_status_counts": _count_review_statuses(inventory_rows),
        "latest_reviewed_at": (None if latest_review is None else latest_review["recorded_at"]),
        "latest_review_status": None if latest_review is None else latest_review["status"],
        "latest_review_operator": (None if latest_review is None else latest_review["operator"]),
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
            isinstance(recorded_at, str) and isinstance(status, str) and isinstance(operator, str)
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
