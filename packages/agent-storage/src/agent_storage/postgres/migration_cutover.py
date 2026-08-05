"""Namespace-scoped PostgreSQL cutover fencing for migration writes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID, uuid4

import psycopg

from agent_storage.postgres.database import PostgresDatabase

_T = TypeVar("_T")


class CutoverConflictError(RuntimeError):
    """Raised when a cutover transition would violate the active fence."""


class PostgresCutoverStore:
    """Namespace-scoped cutover state; runtime writes must use ``run_guarded``."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def prepare(self, *, manifest_sha256: str, cutover_id: UUID | None = None) -> UUID:
        identifier = cutover_id or uuid4()
        _require_digest(manifest_sha256)
        with self._database.connect() as connection:
            connection.execute(
                """INSERT INTO control_plane_cutovers
                (deployment_namespace, cutover_id, state, manifest_sha256)
                VALUES (%s, %s, 'prepared', %s)""",
                (self._database.deployment_namespace, identifier, manifest_sha256),
            )
        return identifier

    def verify(self, cutover_id: UUID, *, manifest_sha256: str) -> None:
        self._transition(cutover_id, "prepared", "verified", manifest_sha256)

    def activate(self, cutover_id: UUID, *, manifest_sha256: str) -> None:
        self._transition(cutover_id, "verified", "active", manifest_sha256)

    def _transition(
        self, cutover_id: UUID, expected: str, target: str, manifest_sha256: str
    ) -> None:
        _require_digest(manifest_sha256)
        try:
            with self._database.connect() as connection:
                cursor = connection.execute(
                    """UPDATE control_plane_cutovers
                    SET state = %s, verified_at = CASE WHEN %s = 'verified'
                        THEN transaction_timestamp() ELSE verified_at END,
                        activated_at = CASE WHEN %s = 'active'
                        THEN transaction_timestamp() ELSE activated_at END
                    WHERE deployment_namespace = %s AND cutover_id = %s
                      AND state = %s AND manifest_sha256 = %s""",
                    (
                        target,
                        target,
                        target,
                        self._database.deployment_namespace,
                        cutover_id,
                        expected,
                        manifest_sha256,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CutoverConflictError(f"invalid cutover transition to {target}")
        except psycopg.errors.UniqueViolation as error:
            raise CutoverConflictError("another active cutover already exists") from error

    def run_guarded(
        self, cutover_id: UUID, manifest_sha256: str, action: Callable[[Any], _T]
    ) -> _T:
        _require_digest(manifest_sha256)
        with self._database.connect() as connection:
            _assert_active(
                connection,
                self._database.deployment_namespace,
                cutover_id,
                manifest_sha256,
            )
            return action(connection)


def _assert_active(connection: Any, namespace: str, cutover_id: UUID, digest: str) -> None:
    row = connection.execute(
        """SELECT state FROM control_plane_cutovers
        WHERE deployment_namespace = %s AND cutover_id = %s
          AND manifest_sha256 = %s""",
        (namespace, cutover_id, digest),
    ).fetchone()
    if row is None or row["state"] != "active":
        raise CutoverConflictError("runtime write requires an active matching cutover")


def _require_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("manifest checksum must be a lowercase SHA-256 digest")
