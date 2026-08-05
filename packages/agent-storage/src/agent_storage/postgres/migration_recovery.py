"""Deterministic SQLite snapshots and PostgreSQL cutover fencing."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID, uuid4

import psycopg
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import WorkspaceProjectionError, rebuild_workspace
from agent_core.domain.events import EventType, SessionEvent
from psycopg import sql

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.migration_snapshot import (
    SnapshotRecord,
    load_sqlite_snapshot,
)
from agent_storage.postgres.model_tool_projections import index_event_in_transaction
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.workspaces import save_workspace_in_transaction

_IMPORT_IDENTITY = "zebra-postgres-migration-v1"
_T = TypeVar("_T")


class CutoverConflictError(RuntimeError):
    """Raised when a cutover transition would violate the active fence."""


class MigrationImportError(RuntimeError):
    """Raised when a snapshot cannot be imported without losing authority."""


@dataclass(frozen=True, slots=True)
class MigrationImportReport:
    deployment_namespace: str
    event_count: int
    projection_count: int
    workspace_count: int
    model_tool_projection_count: int
    manifest_sha256: str


def import_sqlite_event_snapshot(
    directory: str | Path,
    postgres_dsn: str,
    *,
    deployment_namespace: str,
    importer_identity: str,
) -> MigrationImportReport:
    """Import Events first, then rebuild Sessions from the imported Event stream."""
    snapshot = load_sqlite_snapshot(directory)
    if importer_identity != _IMPORT_IDENTITY:
        raise MigrationImportError("restricted migration importer identity required")
    records_by_table: dict[str, list[SnapshotRecord]] = {}
    for record in snapshot.records:
        records_by_table.setdefault(record.table, []).append(record)
    unsupported = set(records_by_table) - {"session_events", "session_projections"}
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise MigrationImportError(f"snapshot contains unsupported authoritative tables: {names}")
    events = _events_from_records(records_by_table.get("session_events", []))
    database = PostgresDatabase(postgres_dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"migration-import:{deployment_namespace}",),
        )
        _require_empty_import_target(connection)
        grouped: dict[str, list[SessionEvent]] = {}
        model_tool_projection_count = 0
        for event in events:
            append_event_in_transaction(connection, deployment_namespace, event)
            grouped.setdefault(str(event.session_id), []).append(event)
            try:
                if index_event_in_transaction(connection, deployment_namespace, event) is not None:
                    model_tool_projection_count += 1
            except (KeyError, TypeError, ValueError) as error:
                raise MigrationImportError(
                    "Event cannot rebuild model/tool projection"
                ) from error
        workspace_count = 0
        for session_events in grouped.values():
            save_session_in_transaction(
                connection,
                deployment_namespace,
                rebuild_session(session_events),
            )
            if any(event.event_type is EventType.TASK_PREPARED for event in session_events):
                try:
                    save_workspace_in_transaction(
                        connection,
                        deployment_namespace,
                        rebuild_workspace(session_events),
                    )
                except WorkspaceProjectionError as error:
                    raise MigrationImportError(
                        "task_prepared Event cannot rebuild workspace projection"
                    ) from error
                workspace_count += 1
    return MigrationImportReport(
        deployment_namespace=deployment_namespace,
        event_count=len(events),
        projection_count=len(grouped),
        workspace_count=workspace_count,
        model_tool_projection_count=model_tool_projection_count,
        manifest_sha256=snapshot.manifest.digest,
    )


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


def _events_from_records(records: Sequence[SnapshotRecord]) -> tuple[SessionEvent, ...]:
    events: list[SessionEvent] = []
    for record in records:
        values = _record_values(
            record,
            {
                "event_id",
                "session_id",
                "sequence",
                "event_type",
                "payload",
                "actor",
                "created_at",
                "causation_id",
                "correlation_id",
                "idempotency_key",
                "policy_version",
                "model_profile",
            },
        )
        payload = values["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as error:
                raise MigrationImportError("session Event payload is not JSON") from error
        if not isinstance(payload, dict):
            raise MigrationImportError("session Event payload must be an object")
        try:
            events.append(SessionEvent.model_validate({**values, "payload": payload}))
        except ValueError as error:
            raise MigrationImportError("session Event record failed validation") from error
    events.sort(key=lambda event: (str(event.session_id), event.sequence))
    expected: dict[str, int] = {}
    for event in events:
        sequence = expected.get(str(event.session_id), 0)
        if event.sequence != sequence:
            raise MigrationImportError("session Event sequence is not contiguous")
        expected[str(event.session_id)] = sequence + 1
    return tuple(events)


def _record_values(record: SnapshotRecord, expected: set[str]) -> dict[str, object]:
    if set(record.columns) != expected or len(record.columns) != len(record.values):
        raise MigrationImportError(f"unexpected {record.table} column contract")
    return dict(zip(record.columns, record.values, strict=True))


def _require_empty_import_target(connection: Any) -> None:
    tables = connection.execute(
        """SELECT table_name FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'
          AND table_name <> 'zebra_schema_migrations'"""
    ).fetchall()
    for table_row in tables:
        table = table_row["table_name"]
        row = connection.execute(
            sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
        ).fetchone()
        if row is None or row["count"] != 0:
            raise MigrationImportError("PostgreSQL import target must be empty")


def _require_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("manifest checksum must be a lowercase SHA-256 digest")
