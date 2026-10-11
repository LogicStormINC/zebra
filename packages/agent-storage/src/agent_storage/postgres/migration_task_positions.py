"""Preserve immutable replay coordinates during a restricted offline import."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from agent_storage.postgres.migration_snapshot import SnapshotRecord


class TaskPositionMigrationError(ValueError):
    """A snapshot cannot retain its published replay coordinate contract."""


def snapshot_task_positions(
    records: Sequence[SnapshotRecord],
) -> dict[UUID, tuple[UUID, int]]:
    positions: dict[UUID, tuple[UUID, int]] = {}
    tasks: dict[UUID, set[int]] = {}
    sessions: dict[str, list[tuple[int, UUID | None, int | None]]] = {}
    for record in records:
        values = dict(zip(record.columns, record.values, strict=True))
        task, position = values.get("task_id"), values.get("task_sequence")
        if (task is None) != (position is None):
            raise TaskPositionMigrationError("snapshot Task coordinates must be paired")
        task_id = None
        session_position: int | None = None
        if task is not None:
            if not isinstance(position, int) or isinstance(position, bool) or position < 0:
                raise TaskPositionMigrationError("snapshot Task position must be nonnegative")
            try:
                task_id = UUID(str(task))
                event_id = UUID(str(values["event_id"]))
            except ValueError as error:
                raise TaskPositionMigrationError("snapshot Task identity is invalid") from error
            occupied = tasks.setdefault(task_id, set())
            if position in occupied or event_id in positions:
                raise TaskPositionMigrationError("snapshot Task coordinates are not unique")
            occupied.add(position)
            positions[event_id] = task_id, position
            session_position = position
        sessions.setdefault(str(values["session_id"]), []).append(
            (int(str(values["sequence"])), task_id, session_position)
        )
    for occupied in tasks.values():
        if occupied != set(range(len(occupied))):
            raise TaskPositionMigrationError("snapshot Task coordinates omit a published prefix")
    for history in sessions.values():
        previous: tuple[UUID, int] | None = None
        unassigned = False
        for _, task_id, position in sorted(history):
            if task_id is None or position is None:
                unassigned = True
                continue
            if unassigned or (previous and (
                previous[0] != task_id or previous[1] >= position
            )):
                raise TaskPositionMigrationError("snapshot Task coordinates invert source order")
            previous = task_id, position
    return positions


def restore_task_positions(
    connection: Any, namespace: str, positions: dict[UUID, tuple[UUID, int]],
) -> None:
    for event_id, (task_id, position) in positions.items():
        updated = connection.execute(
            """UPDATE session_events SET task_id=%s,task_sequence=%s
               WHERE deployment_namespace=%s AND event_id=%s AND task_id IS NULL""",
            (task_id, position, namespace, event_id),
        )
        if updated.rowcount != 1:
            raise TaskPositionMigrationError("snapshot Task Event was not restored exactly once")


def validate_task_position_membership(connection: Any, namespace: str) -> None:
    mismatch = connection.execute(
        """SELECT 1 FROM session_events event LEFT JOIN execution_segments member
             ON member.deployment_namespace=event.deployment_namespace
            AND member.session_id=event.session_id
           WHERE event.deployment_namespace=%s AND
             (event.task_id IS NULL OR member.task_id IS DISTINCT FROM event.task_id)
           LIMIT 1""", (namespace,)
    ).fetchone()
    if mismatch is not None:
        raise TaskPositionMigrationError("snapshot Task position conflicts with canonical lineage")
