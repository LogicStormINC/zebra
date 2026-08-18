from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolResult
from agent_core.ports.effect_ledger import (
    EffectLedgerPort,
    EffectLedgerStatus,
    EffectReservation,
)

from agent_storage.database import SQLiteDatabase


class EffectReplayRejectedError(ValueError):
    """Raised when an effect cannot safely be executed or replayed."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS effect_ledger (
    root_session_id TEXT NOT NULL,
    ledger_key TEXT NOT NULL,
    identity_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (root_session_id, ledger_key)
)
"""


class SQLiteEffectLedger(EffectLedgerPort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        with self._database.connect() as connection:
            connection.execute(_SCHEMA)

    def reserve(
        self,
        root_session_id: SessionId,
        identity: EffectIdentity,
        *,
        explicit_retry: bool = False,
    ) -> EffectReservation:
        now = datetime.now(UTC).isoformat()
        key = identity.ledger_key()
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM effect_ledger WHERE root_session_id = ? AND ledger_key = ?",
                (str(root_session_id), key),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO effect_ledger VALUES (?, ?, ?, ?, 1, NULL, ?, ?)",
                    (
                        str(root_session_id),
                        key,
                        identity.model_dump_json(),
                        EffectLedgerStatus.RESERVED.value,
                        now,
                        now,
                    ),
                )
                return EffectReservation(root_session_id, identity, EffectLedgerStatus.RESERVED, 1)
            status = EffectLedgerStatus(row["status"])
            if status is EffectLedgerStatus.SUCCEEDED:
                return EffectReservation(
                    root_session_id,
                    identity,
                    status,
                    row["attempt"],
                    ToolResult.model_validate_json(row["result_json"]),
                    replay=True,
                )
            if status is EffectLedgerStatus.FAILED_NO_EFFECT and explicit_retry:
                attempt = row["attempt"] + 1
                connection.execute(
                    """
                    UPDATE effect_ledger SET status = ?, attempt = ?, result_json = NULL,
                        updated_at = ? WHERE root_session_id = ? AND ledger_key = ?
                    """,
                    (
                        EffectLedgerStatus.RESERVED.value,
                        attempt,
                        now,
                        str(root_session_id),
                        key,
                    ),
                )
                return EffectReservation(
                    root_session_id, identity, EffectLedgerStatus.RESERVED, attempt
                )
            raise EffectReplayRejectedError(f"effect replay rejected: {status.value}")

    def mark_executing(self, reservation: EffectReservation) -> None:
        self._transition(reservation, EffectLedgerStatus.RESERVED, EffectLedgerStatus.EXECUTING)

    def mark_succeeded(self, reservation: EffectReservation, result: ToolResult) -> None:
        self._transition(
            reservation,
            EffectLedgerStatus.EXECUTING,
            EffectLedgerStatus.SUCCEEDED,
            result=result,
        )

    def mark_failed_no_effect(self, reservation: EffectReservation) -> None:
        self._transition(
            reservation,
            EffectLedgerStatus.EXECUTING,
            EffectLedgerStatus.FAILED_NO_EFFECT,
        )

    def mark_uncertain(self, reservation: EffectReservation) -> None:
        self._transition(reservation, EffectLedgerStatus.EXECUTING, EffectLedgerStatus.UNCERTAIN)

    def terminal_keys(self, root_session_id: SessionId) -> frozenset[str]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT ledger_key FROM effect_ledger
                WHERE root_session_id = ? AND status = 'succeeded'
                """,
                (str(root_session_id),),
            ).fetchall()
        return frozenset(row[0] for row in rows)

    def has_uncertain(self, root_session_id: SessionId) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM effect_ledger WHERE root_session_id = ?
                AND status IN ('reserved', 'executing', 'uncertain') LIMIT 1
                """,
                (str(root_session_id),),
            ).fetchone()
        return row is not None

    def _transition(
        self,
        reservation: EffectReservation,
        expected: EffectLedgerStatus,
        target: EffectLedgerStatus,
        *,
        result: ToolResult | None = None,
    ) -> None:
        result_json = None if result is None else result.model_dump_json()
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE effect_ledger SET status = ?, result_json = ?, updated_at = ?
                WHERE root_session_id = ? AND ledger_key = ? AND status = ? AND attempt = ?
                """,
                (
                    target.value,
                    result_json,
                    datetime.now(UTC).isoformat(),
                    str(reservation.root_session_id),
                    reservation.identity.ledger_key(),
                    expected.value,
                    reservation.attempt,
                ),
            )
            if cursor.rowcount != 1:
                raise EffectReplayRejectedError("effect ledger transition conflict")
