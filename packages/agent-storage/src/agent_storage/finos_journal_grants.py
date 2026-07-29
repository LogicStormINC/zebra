from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from agent_core.domain.identifiers import TaskId

from agent_storage.database import SQLiteDatabase

_CONFLICTED_GRANT_OWNER = "__conflict__"


@dataclass(frozen=True)
class FinosJournalGrant:
    task_id: TaskId
    contract_version: str
    expires_at: datetime
    grant: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.contract_version.strip():
            raise ValueError("FinOS Journal contract_version must not be blank")
        if not self.grant.strip():
            raise ValueError("FinOS Journal grant must not be blank")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("FinOS Journal grant expiry must be timezone-aware")

    @property
    def active(self) -> bool:
        return self.expires_at > datetime.now(UTC)


class SQLiteFinosJournalGrantStore:
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS finos_journal_grants (
                    task_id TEXT PRIMARY KEY,
                    contract_version TEXT NOT NULL,
                    grant TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS finos_journal_grant_digests (
                    grant_digest TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL
                )
                """
            )
            for row in connection.execute(
                "SELECT task_id, grant FROM finos_journal_grants"
            ).fetchall():
                _register_grant_digest(connection, row["task_id"], row["grant"])

    def bind(self, binding: FinosJournalGrant) -> None:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT contract_version, grant, expires_at FROM finos_journal_grants "
                "WHERE task_id = ?",
                (str(binding.task_id),),
            ).fetchone()
            values = (
                binding.contract_version,
                binding.grant,
                binding.expires_at.isoformat(),
            )
            current_expiry = (
                datetime.fromisoformat(row["expires_at"]) if row is not None else None
            )
            if row is not None:
                if (
                    row["contract_version"] == binding.contract_version
                    and row["grant"] == binding.grant
                    and current_expiry == binding.expires_at
                ):
                    owner = _grant_owner(connection, binding.grant)
                    if owner != str(binding.task_id):
                        raise ValueError("FinOS Journal grant ownership is conflicted")
                    return
                if (
                    row["contract_version"] != binding.contract_version
                    or current_expiry is None
                    or binding.expires_at < current_expiry
                ):
                    raise ValueError("FinOS Journal grant rotation is stale or incompatible")
            digest = _grant_digest(binding.grant)
            if connection.execute(
                "SELECT 1 FROM finos_journal_grant_digests WHERE grant_digest = ?",
                (digest,),
            ).fetchone() is not None:
                raise ValueError("FinOS Journal grant was already used")
            connection.execute(
                "INSERT INTO finos_journal_grant_digests VALUES (?, ?)",
                (digest, str(binding.task_id)),
            )
            if row is not None:
                connection.execute(
                    "UPDATE finos_journal_grants "
                    "SET contract_version = ?, grant = ?, expires_at = ? "
                    "WHERE task_id = ?",
                    (*values, str(binding.task_id)),
                )
                return
            connection.execute(
                "INSERT INTO finos_journal_grants VALUES (?, ?, ?, ?)",
                (str(binding.task_id), *values),
            )

    def get(self, task_id: TaskId) -> FinosJournalGrant | None:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM finos_journal_grants WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
            if row is None or _grant_owner(connection, row["grant"]) != str(task_id):
                return None
            return FinosJournalGrant(
                task_id=task_id,
                contract_version=row["contract_version"],
                grant=row["grant"],
                expires_at=datetime.fromisoformat(row["expires_at"]),
            )


def _register_grant_digest(
    connection: sqlite3.Connection,
    task_id: str,
    grant: str,
) -> None:
    digest = _grant_digest(grant)
    row = connection.execute(
        "SELECT task_id FROM finos_journal_grant_digests WHERE grant_digest = ?",
        (digest,),
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO finos_journal_grant_digests VALUES (?, ?)",
            (digest, task_id),
        )
    elif row["task_id"] not in {task_id, _CONFLICTED_GRANT_OWNER}:
        connection.execute(
            "UPDATE finos_journal_grant_digests SET task_id = ? WHERE grant_digest = ?",
            (_CONFLICTED_GRANT_OWNER, digest),
        )


def _grant_owner(connection: sqlite3.Connection, grant: str) -> str | None:
    row = connection.execute(
        "SELECT task_id FROM finos_journal_grant_digests WHERE grant_digest = ?",
        (_grant_digest(grant),),
    ).fetchone()
    return row["task_id"] if row is not None else None


def _grant_digest(grant: str) -> str:
    return sha256(grant.encode()).hexdigest()
