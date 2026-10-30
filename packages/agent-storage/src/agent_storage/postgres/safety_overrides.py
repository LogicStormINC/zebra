"""Control-plane safety overrides: bounded failure counts and terminal backstops.

Dead-letter/watchdog/zombie terminalization writes here when the event-sourced
path is unavailable or untrusted. Readers must treat an existing terminal
override (kind IN dead_letter/watchdog/zombie_repair) as authoritative over
any in-stream active status.

All mutations are single-statement upserts so concurrent workers converge on
the same row without read-modify-write races.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import class_row

TERMINAL_KINDS = ("dead_letter", "watchdog", "zombie_repair")


@dataclass(frozen=True, slots=True)
class SafetyOverride:
    session_id: str
    kind: str
    reason: str
    attempts: int
    shadow: bool
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS and not self.shadow


class PostgresSafetyOverrideStore:
    """Bounded failure accounting plus the control-plane terminal channel."""

    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self._connection = connection

    def record_failure(
        self,
        *,
        namespace: str,
        session_id: str,
        reason: str,
        structural: bool,
        max_attempts: int,
        shadow: bool,
    ) -> SafetyOverride:
        """Count one recovery failure; escalate to dead_letter at the cap.

        Only structural failures (recorder/sequence/type errors) count: a
        transient storage or network blip must never dead-letter a session
        that would recover on the next attempt.
        """
        now = datetime.now(UTC)
        with self._connection.transaction():
            row = self._connection.execute(
                """
                INSERT INTO agent_safety_overrides
                    (deployment_namespace, session_id, kind, reason, attempts,
                     shadow, created_at, updated_at)
                VALUES (%s, %s, 'failure_count', %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, session_id) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    attempts = CASE
                        WHEN agent_safety_overrides.kind = 'failure_count'
                        THEN agent_safety_overrides.attempts + 1
                        ELSE agent_safety_overrides.attempts
                    END,
                    updated_at = EXCLUDED.updated_at
                RETURNING session_id::text, kind, reason, attempts, shadow, updated_at
                """,
                (namespace, session_id, reason[:500], 1 if structural else 0, shadow, now, now),
            ).fetchone()
        if (
            row is not None
            and row[1] == "failure_count"
            and structural
            and row[3] >= max_attempts
        ):
            return self.finalize(
                namespace=namespace,
                session_id=session_id,
                kind="dead_letter",
                reason=f"recovery_dead_letter:{reason[:200]}",
                diagnostics=json.dumps(
                    {"attempts": row[3], "last_error": reason[:500]},
                    ensure_ascii=False,
                ),
                shadow=shadow,
            )
        assert row is not None
        return SafetyOverride(*row)

    def finalize(
        self,
        *,
        namespace: str,
        session_id: str,
        kind: str,
        reason: str,
        diagnostics: str = "",
        shadow: bool = False,
    ) -> SafetyOverride:
        """Write (idempotently) a terminal control-plane override."""
        if kind not in TERMINAL_KINDS:
            raise ValueError("invalid safety override kind")
        now = datetime.now(UTC)
        with self._connection.transaction():
            row = self._connection.execute(
                """
                INSERT INTO agent_safety_overrides
                    (deployment_namespace, session_id, kind, reason, diagnostics,
                     attempts, shadow, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s)
                ON CONFLICT (deployment_namespace, session_id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    reason = EXCLUDED.reason,
                    diagnostics = EXCLUDED.diagnostics,
                    updated_at = EXCLUDED.updated_at
                WHERE agent_safety_overrides.kind = 'failure_count'
                   OR agent_safety_overrides.kind <> EXCLUDED.kind
                RETURNING session_id::text, kind, reason, attempts, shadow, updated_at
                """,
                (namespace, session_id, kind, reason[:500], diagnostics[:4000], shadow, now, now),
            ).fetchone()
        if row is None:
            return self.get(namespace=namespace, session_id=session_id)  # type: ignore[return-value]
        return SafetyOverride(*row)

    def get(self, *, namespace: str, session_id: str) -> SafetyOverride | None:
        with self._connection.cursor(row_factory=class_row(SafetyOverride)) as cursor:
            cursor.execute(
                """
                SELECT session_id::text, kind, reason, attempts, shadow, updated_at
                FROM agent_safety_overrides
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (namespace, session_id),
            )
            return cursor.fetchone()

    def terminal(self, *, namespace: str, session_id: str) -> SafetyOverride | None:
        """Return the override only when it is an effective terminal state."""
        record = self.get(namespace=namespace, session_id=session_id)
        return record if record is not None and record.is_terminal else None
