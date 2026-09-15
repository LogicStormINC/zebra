"""Atomic PostgreSQL due selection and Task Schedule Firing recovery."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from agent_core.application.task_schedule_time import next_fire_at
from agent_core.domain.identifiers import TaskScheduleFiringId, task_schedule_firing_id
from agent_core.domain.task_schedules import (
    OnceScheduleTrigger,
    ScheduleFiringStatus,
    ScheduleOverlapPolicy,
    TaskSchedule,
    TaskScheduleFiring,
)
from agent_core.ports.task_schedules import TaskScheduleConflictError
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_schedule_rows import decode_firing, decode_schedule
from agent_storage.postgres.task_schedules import _SCHEDULE_COLUMNS

_FIRING_COLUMNS = """fire_id, schedule_id, schedule_version, scheduled_for,
    status, task_id, attempt, failure_code, claimed_by, claim_expires_at,
    created_at, dispatched_at, completed_at"""


class PostgresTaskScheduleFiringStore(PostgresDatabase):
    def claim_due(
        self,
        *,
        claimant: str,
        limit: int,
        claim_ttl_seconds: int,
    ) -> tuple[TaskScheduleFiring, ...]:
        claimant = claimant.strip()
        if not claimant or len(claimant) > 256:
            raise ValueError("claimant must be non-blank and at most 256 characters")
        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if (
            isinstance(claim_ttl_seconds, bool)
            or claim_ttl_seconds < 1
            or claim_ttl_seconds > 3_600
        ):
            raise ValueError("claim_ttl_seconds must be between 1 and 3600")
        with self.connect() as connection:
            now = self._database_now(connection)
            claimed = self._recover_expired(
                connection, claimant, now, limit, claim_ttl_seconds
            )
            remaining = limit - len(claimed)
            if remaining:
                claimed.extend(
                    self._create_due(
                        connection, claimant, now, remaining, claim_ttl_seconds
                    )
                )
            return tuple(claimed)

    def get_firing(
        self,
        fire_id: TaskScheduleFiringId,
    ) -> TaskScheduleFiring | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT " + _FIRING_COLUMNS
                + " FROM task_schedule_firings WHERE deployment_namespace = %s "
                "AND fire_id = %s",
                (self.deployment_namespace, fire_id),
            ).fetchone()
        return decode_firing(row) if row is not None else None

    def settle_firing(
        self,
        firing: TaskScheduleFiring,
        *,
        expected_status: ScheduleFiringStatus,
        expected_claim_expiry: datetime | None,
    ) -> TaskScheduleFiring:
        firing = TaskScheduleFiring.model_validate(firing.model_dump())
        with self.connect() as connection:
            current_row = connection.execute(
                "SELECT " + _FIRING_COLUMNS
                + " FROM task_schedule_firings WHERE deployment_namespace = %s "
                "AND fire_id = %s FOR UPDATE",
                (self.deployment_namespace, firing.fire_id),
            ).fetchone()
            if current_row is None:
                raise TaskScheduleConflictError("Schedule Firing does not exist")
            current = decode_firing(current_row)
            if (
                current.status is not expected_status
                or current.claim_expires_at != expected_claim_expiry
                or current.schedule_id != firing.schedule_id
                or current.schedule_version != firing.schedule_version
                or current.scheduled_for != firing.scheduled_for
                or current.created_at != firing.created_at
                or current.claimed_by != firing.claimed_by
            ):
                raise TaskScheduleConflictError("Schedule Firing identity, state or claim changed")
            row = connection.execute(
                "UPDATE task_schedule_firings SET status = %s, task_id = %s, "
                "attempt = %s, failure_code = %s, claimed_by = %s, claim_expires_at = %s, "
                "dispatched_at = %s, completed_at = %s WHERE deployment_namespace = %s "
                "AND fire_id = %s AND status = %s "
                "AND claim_expires_at IS NOT DISTINCT FROM %s RETURNING " + _FIRING_COLUMNS,
                (
                    firing.status,
                    firing.task_id,
                    firing.attempt,
                    firing.failure_code,
                    firing.claimed_by,
                    firing.claim_expires_at,
                    firing.dispatched_at,
                    firing.completed_at,
                    self.deployment_namespace,
                    firing.fire_id,
                    expected_status,
                    expected_claim_expiry,
                ),
            ).fetchone()
        if row is None:
            raise TaskScheduleConflictError("Schedule Firing state or claim changed")
        return decode_firing(row)

    @staticmethod
    def _database_now(connection: Any) -> datetime:
        row = connection.execute("SELECT clock_timestamp() AS now").fetchone()
        if row is None or not isinstance(row.get("now"), datetime):
            raise RuntimeError("PostgreSQL clock did not return a timestamp")
        return cast(datetime, row["now"])

    def _recover_expired(
        self,
        connection: Any,
        claimant: str,
        now: datetime,
        limit: int,
        ttl: int,
    ) -> list[TaskScheduleFiring]:
        rows = connection.execute(
            "SELECT " + _FIRING_COLUMNS
            + " FROM task_schedule_firings WHERE deployment_namespace = %s "
            "AND status = 'materializing' AND claim_expires_at <= %s "
            "ORDER BY claim_expires_at, scheduled_for, fire_id "
            "LIMIT %s FOR UPDATE SKIP LOCKED",
            (self.deployment_namespace, now, limit),
        ).fetchall()
        recovered: list[TaskScheduleFiring] = []
        expires = now + timedelta(seconds=ttl)
        for row in rows:
            current = decode_firing(row)
            changed = connection.execute(
                "UPDATE task_schedule_firings SET claimed_by = %s, claim_expires_at = %s, "
                "attempt = attempt + 1 WHERE deployment_namespace = %s AND fire_id = %s "
                "AND status = 'materializing' AND claim_expires_at = %s RETURNING "
                + _FIRING_COLUMNS,
                (claimant, expires, self.deployment_namespace, current.fire_id,
                 current.claim_expires_at),
            ).fetchone()
            if changed is not None:
                recovered.append(decode_firing(changed))
        return recovered

    def _create_due(
        self,
        connection: Any,
        claimant: str,
        now: datetime,
        limit: int,
        ttl: int,
    ) -> list[TaskScheduleFiring]:
        rows = connection.execute(
            "SELECT " + _SCHEDULE_COLUMNS
            + " FROM task_schedules WHERE deployment_namespace = %s "
            "AND status = 'active' AND next_fire_at <= %s "
            "ORDER BY next_fire_at, schedule_id LIMIT %s FOR UPDATE SKIP LOCKED",
            (self.deployment_namespace, now, limit),
        ).fetchall()
        claimed: list[TaskScheduleFiring] = []
        for row in rows:
            schedule = decode_schedule(row)
            firing = self._new_firing(connection, schedule, claimant, now, ttl)
            inserted = self._insert_firing(connection, firing)
            self._advance_schedule(connection, schedule, now)
            if inserted is not None and inserted.status is ScheduleFiringStatus.MATERIALIZING:
                claimed.append(inserted)
        return claimed

    def _new_firing(
        self,
        connection: Any,
        schedule: TaskSchedule,
        claimant: str,
        now: datetime,
        ttl: int,
    ) -> TaskScheduleFiring:
        scheduled_for = schedule.next_fire_at
        if scheduled_for is None:
            raise RuntimeError("locked active schedule has no next_fire_at")
        failure_code: str | None = None
        if (now - scheduled_for).total_seconds() > schedule.misfire_grace_seconds:
            failure_code = "misfire_grace_expired"
        elif schedule.overlap_policy is ScheduleOverlapPolicy.FORBID:
            overlap = connection.execute(
                "SELECT 1 FROM task_schedule_firings WHERE deployment_namespace = %s "
                "AND schedule_id = %s AND status IN ('materializing', 'dispatched') LIMIT 1",
                (self.deployment_namespace, schedule.schedule_id),
            ).fetchone()
            if overlap is not None:
                failure_code = "overlap_forbidden"
        terminal = failure_code is not None
        return TaskScheduleFiring(
            fire_id=task_schedule_firing_id(schedule.schedule_id, scheduled_for),
            schedule_id=schedule.schedule_id,
            schedule_version=schedule.schedule_version,
            scheduled_for=scheduled_for,
            status=(ScheduleFiringStatus.SKIPPED if terminal
                    else ScheduleFiringStatus.MATERIALIZING),
            attempt=(0 if terminal else 1),
            failure_code=failure_code,
            claimed_by=(None if terminal else claimant),
            claim_expires_at=(None if terminal else now + timedelta(seconds=ttl)),
            created_at=now,
            completed_at=(now if terminal else None),
        )

    def _insert_firing(
        self,
        connection: Any,
        firing: TaskScheduleFiring,
    ) -> TaskScheduleFiring | None:
        row = connection.execute(
            "INSERT INTO task_schedule_firings (deployment_namespace, "
            + _FIRING_COLUMNS
            + ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (deployment_namespace, schedule_id, scheduled_for) DO NOTHING "
            "RETURNING " + _FIRING_COLUMNS,
            (self.deployment_namespace, *(
                getattr(firing, field.strip()) for field in _FIRING_COLUMNS.split(",")
            )),
        ).fetchone()
        return decode_firing(row) if row is not None else None

    def _advance_schedule(
        self,
        connection: Any,
        schedule: TaskSchedule,
        now: datetime,
    ) -> None:
        scheduled_for = schedule.next_fire_at
        if scheduled_for is None:
            raise RuntimeError("active schedule lost next_fire_at")
        if isinstance(schedule.trigger, OnceScheduleTrigger):
            advanced = schedule.complete(at=now, last_fire_at=scheduled_for)
        else:
            following = next_fire_at(schedule.trigger, timezone_name=schedule.timezone, after=now)
            if following is None:
                raise RuntimeError("recurring schedule did not produce a next occurrence")
            advanced = TaskSchedule.model_validate(
                {**schedule.model_dump(), "next_fire_at": following,
                 "last_fire_at": scheduled_for, "updated_at": now}
            )
        row = connection.execute(
            "UPDATE task_schedules SET status = %s, schedule_version = %s, "
            "next_fire_at = %s, last_fire_at = %s, updated_at = %s, payload = %s "
            "WHERE deployment_namespace = %s AND schedule_id = %s "
            "AND status = 'active' AND schedule_version = %s "
            "AND next_fire_at = %s RETURNING schedule_id",
            (advanced.status, advanced.schedule_version, advanced.next_fire_at,
             advanced.last_fire_at, advanced.updated_at,
             Jsonb(advanced.model_dump(mode="json")),
             self.deployment_namespace, schedule.schedule_id,
             schedule.schedule_version, scheduled_for),
        ).fetchone()
        if row is None:
            raise TaskScheduleConflictError("locked Task Schedule changed during advancement")
