from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_storage.database import SQLiteDatabase


@dataclass(frozen=True)
class SkillStateRecord:
    name: str
    scope: str
    enabled: bool
    updated_at: datetime
    operator: str | None


class SQLiteSkillsStateStore:
    """Persistent enable/disable state for skill components.

    Keyed by ``(name, scope)``. A missing row means the component keeps its
    default enabled state; only an explicit ``enabled = 0`` row disables it.
    The catalog treats ``state=None`` as "no filtering" (backward compatible)
    and otherwise filters out every component whose ``(name, scope)`` is marked
    disabled here.
    """

    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def set_enabled(
        self,
        *,
        name: str,
        scope: str,
        enabled: bool,
        operator: str | None,
        updated_at: datetime | None = None,
    ) -> SkillStateRecord:
        record = SkillStateRecord(
            name=name,
            scope=scope,
            enabled=enabled,
            updated_at=updated_at or datetime.now(UTC),
            operator=operator,
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO skills_state (name, scope, enabled, updated_at, operator)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name, scope) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at,
                    operator = excluded.operator
                """,
                (
                    record.name,
                    record.scope,
                    1 if record.enabled else 0,
                    record.updated_at.isoformat(),
                    record.operator,
                ),
            )
        return record

    def get_state(self, *, name: str, scope: str) -> SkillStateRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT name, scope, enabled, updated_at, operator
                FROM skills_state
                WHERE name = ? AND scope = ?
                """,
                (name, scope),
            ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def list_states(self) -> tuple[SkillStateRecord, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT name, scope, enabled, updated_at, operator
                FROM skills_state
                ORDER BY name, scope
                """
            ).fetchall()
        return tuple(_row_to_record(row) for row in rows)

    def disabled_components(self) -> frozenset[tuple[str, str]]:
        """The ``(name, scope)`` pairs explicitly disabled (used to filter the catalog)."""
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT name, scope FROM skills_state WHERE enabled = 0"
            ).fetchall()
        return frozenset((row["name"], row["scope"]) for row in rows)

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS skills_state (
                    name TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    operator TEXT,
                    PRIMARY KEY (name, scope)
                )
                """
            )


def _row_to_record(row: Any) -> SkillStateRecord:
    return SkillStateRecord(
        name=row["name"],
        scope=row["scope"],
        enabled=bool(row["enabled"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        operator=row["operator"],
    )
