"""Owner-scoped PostgreSQL Task Schedule and authority storage."""

from __future__ import annotations

from typing import Any

from agent_core.domain.identifiers import TaskScheduleId
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import TaskSchedule
from agent_core.ports.task_schedules import TaskScheduleConflictError
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_schedule_rows import (
    decode_authority,
    decode_schedule,
    owner_values,
    validate_owner,
)

_SCHEDULE_COLUMNS = """deployment_namespace, schedule_id, tenant_id, workspace_id,
    principal_id, host_app_id, title, status, schedule_version, next_fire_at,
    last_fire_at, authority_binding_id, created_at, updated_at, payload"""
_AUTHORITY_COLUMNS = """deployment_namespace, binding_id, schedule_id, tenant_id,
    workspace_id, principal_id, host_app_id, binding_revision, revoked_at, payload"""
_OWNER = """deployment_namespace = %s AND tenant_id = %s AND workspace_id = %s
    AND principal_id = %s AND host_app_id = %s"""


class PostgresTaskScheduleStore(PostgresDatabase):
    def create(
        self,
        schedule: TaskSchedule,
        authority: ScheduleAuthorityBinding,
    ) -> TaskSchedule:
        schedule = TaskSchedule.model_validate(schedule.model_dump())
        authority = ScheduleAuthorityBinding.model_validate(authority.model_dump())
        owner = validate_owner(schedule.owner, self.deployment_namespace)
        if (
            authority.owner != owner
            or authority.schedule_id != schedule.schedule_id
            or authority.binding_id != schedule.authority_binding_id
        ):
            raise ValueError("schedule and authority binding disagree")
        try:
            with self.connect() as connection:
                self._insert_authority(connection, authority)
                self._insert_schedule(connection, schedule)
        except UniqueViolation as exc:
            raise TaskScheduleConflictError("Task Schedule identity already exists") from exc
        return schedule

    def get(
        self,
        schedule_id: TaskScheduleId,
        *,
        owner: ScheduleOwner,
    ) -> TaskSchedule | None:
        owner = validate_owner(owner, self.deployment_namespace)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT " + _SCHEDULE_COLUMNS + " FROM task_schedules WHERE "
                + _OWNER
                + " AND schedule_id = %s",
                (self.deployment_namespace, *owner_values(owner), schedule_id),
            ).fetchone()
        return decode_schedule(row) if row is not None else None

    def get_authority(
        self,
        schedule_id: TaskScheduleId,
        *,
        owner: ScheduleOwner,
    ) -> ScheduleAuthorityBinding | None:
        owner = validate_owner(owner, self.deployment_namespace)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT " + ", ".join(f"a.{part.strip()}" for part in _AUTHORITY_COLUMNS.split(","))
                + " FROM schedule_authority_bindings a JOIN task_schedules s ON "
                "s.deployment_namespace = a.deployment_namespace "
                "AND s.schedule_id = a.schedule_id "
                "AND s.authority_binding_id = a.binding_id WHERE "
                + " AND ".join(f"s.{part.strip()}" for part in _OWNER.split(" AND "))
                + " AND s.schedule_id = %s",
                (self.deployment_namespace, *owner_values(owner), schedule_id),
            ).fetchone()
        return decode_authority(row) if row is not None else None

    def list_for_owner(
        self,
        owner: ScheduleOwner,
        *,
        limit: int,
    ) -> tuple[TaskSchedule, ...]:
        owner = validate_owner(owner, self.deployment_namespace)
        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT " + _SCHEDULE_COLUMNS + " FROM task_schedules WHERE "
                + _OWNER
                + " ORDER BY updated_at DESC, schedule_id LIMIT %s",
                (self.deployment_namespace, *owner_values(owner), limit),
            ).fetchall()
        return tuple(decode_schedule(row) for row in rows)

    def revoke_authority(
        self,
        authority: ScheduleAuthorityBinding,
        *,
        expected_revision: int,
    ) -> ScheduleAuthorityBinding:
        authority = ScheduleAuthorityBinding.model_validate(authority.model_dump())
        owner = validate_owner(authority.owner, self.deployment_namespace)
        if authority.revoked_at is None:
            raise ValueError("revoked authority must carry revoked_at")
        if authority.binding_revision != expected_revision + 1:
            raise ValueError("revoked authority must advance expected_revision exactly once")
        with self.connect() as connection:
            row = connection.execute(
                "UPDATE schedule_authority_bindings SET binding_revision = %s, "
                "revoked_at = %s, payload = %s WHERE deployment_namespace = %s "
                "AND tenant_id = %s AND workspace_id = %s AND principal_id = %s "
                "AND host_app_id = %s AND schedule_id = %s AND binding_id = %s "
                "AND binding_revision = %s AND revoked_at IS NULL RETURNING "
                + _AUTHORITY_COLUMNS,
                (
                    authority.binding_revision,
                    authority.revoked_at,
                    Jsonb(authority.model_dump(mode="json")),
                    self.deployment_namespace,
                    *owner_values(owner),
                    authority.schedule_id,
                    authority.binding_id,
                    expected_revision,
                ),
            ).fetchone()
        if row is None:
            raise TaskScheduleConflictError("Schedule authority revision or ownership changed")
        return decode_authority(row)

    def update(
        self,
        schedule: TaskSchedule,
        *,
        expected_version: int,
    ) -> TaskSchedule:
        schedule = TaskSchedule.model_validate(schedule.model_dump())
        owner = validate_owner(schedule.owner, self.deployment_namespace)
        if schedule.schedule_version != expected_version + 1:
            raise ValueError("updated schedule must advance expected_version exactly once")
        values = self._schedule_mutable_values(schedule)
        with self.connect() as connection:
            row = connection.execute(
                "UPDATE task_schedules SET title = %s, status = %s, schedule_version = %s, "
                "next_fire_at = %s, last_fire_at = %s, authority_binding_id = %s, "
                "updated_at = %s, payload = %s WHERE "
                + _OWNER
                + " AND schedule_id = %s AND schedule_version = %s RETURNING "
                + _SCHEDULE_COLUMNS,
                (*values, self.deployment_namespace, *owner_values(owner),
                 schedule.schedule_id, expected_version),
            ).fetchone()
        if row is None:
            raise TaskScheduleConflictError("Task Schedule version or ownership changed")
        return decode_schedule(row)

    def _insert_authority(self, connection: Any, authority: ScheduleAuthorityBinding) -> None:
        connection.execute(
            "INSERT INTO schedule_authority_bindings (" + _AUTHORITY_COLUMNS
            + ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (self.deployment_namespace, authority.binding_id, authority.schedule_id,
             *owner_values(authority.owner), authority.binding_revision,
             authority.revoked_at, Jsonb(authority.model_dump(mode="json"))),
        )

    def _insert_schedule(self, connection: Any, schedule: TaskSchedule) -> None:
        connection.execute(
            "INSERT INTO task_schedules (" + _SCHEDULE_COLUMNS
            + ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (self.deployment_namespace, schedule.schedule_id, *owner_values(schedule.owner),
             *self._schedule_mutable_values(schedule)[0:6], schedule.created_at,
             schedule.updated_at, Jsonb(schedule.model_dump(mode="json"))),
        )

    @staticmethod
    def _schedule_mutable_values(schedule: TaskSchedule) -> tuple[object, ...]:
        return (
            schedule.title, schedule.status, schedule.schedule_version,
            schedule.next_fire_at, schedule.last_fire_at, schedule.authority_binding_id,
            schedule.updated_at, Jsonb(schedule.model_dump(mode="json")),
        )
