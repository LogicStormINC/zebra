"""Deterministic next-fire calculation for user-level schedules."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent_core.domain.task_schedules import (
    IntervalScheduleTrigger,
    OnceScheduleTrigger,
    ScheduleTrigger,
    WeeklyScheduleTrigger,
)

_MAX_CALENDAR_SEARCH_DAYS = 370
_MAX_DST_GAP_MINUTES = 180


def schedule_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc


def next_fire_at(
    trigger: ScheduleTrigger,
    *,
    timezone_name: str,
    after: datetime,
) -> datetime | None:
    """Return the first UTC occurrence strictly after ``after``."""

    after_utc = _aware_utc(after)
    timezone = schedule_timezone(timezone_name)
    if isinstance(trigger, OnceScheduleTrigger):
        return trigger.fire_at if trigger.fire_at > after_utc else None
    if isinstance(trigger, IntervalScheduleTrigger):
        if trigger.anchor_at > after_utc:
            return trigger.anchor_at
        elapsed = (after_utc - trigger.anchor_at).total_seconds()
        steps = int(elapsed // trigger.every_seconds) + 1
        return trigger.anchor_at + timedelta(seconds=steps * trigger.every_seconds)

    local_after = after_utc.astimezone(timezone)
    for offset in range(_MAX_CALENDAR_SEARCH_DAYS):
        candidate_date = local_after.date() + timedelta(days=offset)
        if (
            isinstance(trigger, WeeklyScheduleTrigger)
            and candidate_date.weekday() not in trigger.weekdays
        ):
            continue
        candidate = _resolve_wall_time(candidate_date, trigger.local_time, timezone)
        if candidate > after_utc:
            return candidate
    raise ValueError("calendar trigger did not produce an occurrence within the search horizon")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("after must be timezone-aware")
    return value.astimezone(UTC)


def _resolve_wall_time(local_date: date, local_time: object, timezone: ZoneInfo) -> datetime:
    from datetime import time

    if not isinstance(local_time, time):
        raise TypeError("local_time must be datetime.time")
    naive = datetime.combine(local_date, local_time)
    for minute in range(_MAX_DST_GAP_MINUTES + 1):
        candidate = naive + timedelta(minutes=minute)
        valid = _valid_utc_candidates(candidate, timezone)
        if valid:
            # A fold has two valid instants. Picking the earlier one guarantees
            # one wall-clock firing; the later fold is never emitted separately.
            return min(valid)
    raise ValueError("local wall time gap exceeds the supported DST horizon")


def _valid_utc_candidates(naive: datetime, timezone: ZoneInfo) -> tuple[datetime, ...]:
    candidates: set[datetime] = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=timezone, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(timezone).replace(tzinfo=None) == naive:
            candidates.add(utc)
    return tuple(sorted(candidates))
