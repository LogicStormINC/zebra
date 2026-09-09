"""Immutable extension inputs; persistence is not admission or execution authority."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_core.domain.execution_authority_support import digest
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionDigest, ExtensionScope, OpaqueExtensionId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.extension_snapshots import (
    ExtensionSnapshotConflictError,
    ExtensionSnapshotIntegrityError,
    ExtensionSnapshotNotFoundError,
)
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter, ValidationError

from agent_storage.postgres.database import PostgresDatabase

_ID = TypeAdapter(OpaqueExtensionId)
_DIGEST = TypeAdapter(ExtensionDigest)
_COLUMNS = """key_digest, deployment_namespace, authority_issuer, namespace_id,
    principal_id, workspace_id, session_id, turn_id"""
_KEY = """key_digest = %s AND deployment_namespace = %s AND authority_issuer = %s
    AND namespace_id = %s AND principal_id = %s AND workspace_id = %s
    AND session_id = %s AND turn_id = %s"""


def _validate_scope(scope: ExtensionScope) -> ExtensionScope:
    if not isinstance(scope, ExtensionScope):
        raise TypeError("scope must be an ExtensionScope")
    return ExtensionScope.model_validate(scope.model_dump())


def _snapshot_key(
    deployment_namespace: str,
    scope: ExtensionScope,
    session_id: str,
    turn_id: str,
) -> tuple[str, ...]:
    coordinates = {
        "deployment_namespace": deployment_namespace,
        **scope.model_dump(),
        "session_id": session_id,
        "turn_id": turn_id,
    }
    # ponytail: compact index avoids the B-tree size ceiling on opaque coordinates;
    # every lookup also compares all original coordinates, including on replay.
    return (digest(coordinates), *coordinates.values())


def _decode_snapshot(
    row: dict[str, Any],
    scope: ExtensionScope,
    session_id: str,
    turn_id: str,
) -> ExtensionSnapshot:
    try:
        snapshot = ExtensionSnapshot.model_validate(row["payload"])
        stored_digest = _DIGEST.validate_python(row["snapshot_digest"])
    except (ValidationError, TypeError, KeyError) as exc:
        raise ExtensionSnapshotIntegrityError("invalid stored extension snapshot") from exc
    if (
        snapshot.scope != scope
        or snapshot.session_id != session_id
        or snapshot.turn_id != turn_id
        or snapshot.digest != stored_digest
    ):
        raise ExtensionSnapshotIntegrityError("stored snapshot identity or digest disagrees")
    return snapshot


class PostgresExtensionSnapshotStore(PostgresDatabase):
    """Each off-thread operation owns a connection and transaction.

    Runtime must later bind a trusted expected digest and authorize live operations;
    this adapter alone grants no authority and has no production Worker/API caller.
    """

    async def save(self, *, scope: ExtensionScope, snapshot: ExtensionSnapshot) -> None:
        scope = self._validate_scope(scope)
        if not isinstance(snapshot, ExtensionSnapshot):
            raise TypeError("snapshot must be an ExtensionSnapshot")
        snapshot = ExtensionSnapshot.model_validate(snapshot.model_dump())
        if snapshot.scope != scope:
            raise ValueError("snapshot scope disagrees with supplied scope")
        await asyncio.to_thread(self._save, scope, snapshot)

    async def get(
        self,
        *,
        scope: ExtensionScope,
        session_id: str,
        turn_id: str,
        expected_digest: str,
    ) -> ExtensionSnapshot:
        scope = self._validate_scope(scope)
        session_id = _ID.validate_python(session_id)
        turn_id = _ID.validate_python(turn_id)
        expected_digest = _DIGEST.validate_python(expected_digest)
        return await asyncio.to_thread(self._get, scope, session_id, turn_id, expected_digest)

    async def exists(
        self, *, scope: ExtensionScope, session_id: str, turn_id: str
    ) -> bool:
        scope = self._validate_scope(scope)
        session_id = _ID.validate_python(session_id)
        turn_id = _ID.validate_python(turn_id)
        return await asyncio.to_thread(self._exists, scope, session_id, turn_id)

    def resolve_task_ceiling(self, *, session_id: str) -> ExtensionTaskCeiling:
        session_id = _ID.validate_python(session_id)
        with self.connect() as connection:
            return resolve_extension_task_ceiling_in_transaction(
                connection,
                self.deployment_namespace,
                session_id,
            )

    @staticmethod
    def _validate_scope(scope: ExtensionScope) -> ExtensionScope:
        return _validate_scope(scope)

    def _key(self, scope: ExtensionScope, session_id: str, turn_id: str) -> tuple[str, ...]:
        return _snapshot_key(self.deployment_namespace, scope, session_id, turn_id)

    @staticmethod
    def _decode(
        row: dict[str, Any],
        scope: ExtensionScope,
        session_id: str,
        turn_id: str,
    ) -> ExtensionSnapshot:
        return _decode_snapshot(row, scope, session_id, turn_id)

    def _save(self, scope: ExtensionScope, snapshot: ExtensionSnapshot) -> None:
        with self.connect() as connection:
            save_extension_snapshot_in_transaction(
                connection, self.deployment_namespace, scope, snapshot
            )

    def _get(
        self,
        scope: ExtensionScope,
        session_id: str,
        turn_id: str,
        expected_digest: str,
    ) -> ExtensionSnapshot:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT snapshot_digest, payload FROM turn_extension_snapshots WHERE " + _KEY,
                self._key(scope, session_id, turn_id),
            ).fetchone()
            if row is None:
                raise ExtensionSnapshotNotFoundError("snapshot not found in supplied scope")
            snapshot = self._decode(row, scope, session_id, turn_id)
            if snapshot.digest != expected_digest:
                raise ExtensionSnapshotIntegrityError("snapshot disagrees with trusted digest")
            return snapshot

    def _exists(self, scope: ExtensionScope, session_id: str, turn_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM turn_extension_snapshots WHERE "
                + _KEY
                + ") AS snapshot_exists",
                self._key(scope, session_id, turn_id),
            ).fetchone()
            if row is None:
                raise ExtensionSnapshotIntegrityError("snapshot existence probe returned no row")
            return bool(row["snapshot_exists"])


def save_extension_snapshot_in_transaction(
    connection: Any,
    deployment_namespace: str,
    scope: ExtensionScope,
    snapshot: ExtensionSnapshot,
) -> None:
    """Persist one immutable snapshot inside the caller's transaction."""
    scope = _validate_scope(scope)
    if not isinstance(snapshot, ExtensionSnapshot):
        raise TypeError("snapshot must be an ExtensionSnapshot")
    snapshot = ExtensionSnapshot.model_validate(snapshot.model_dump())
    if snapshot.scope != scope:
        raise ValueError("snapshot scope disagrees with supplied scope")
    key = _snapshot_key(deployment_namespace, scope, snapshot.session_id, snapshot.turn_id)
    connection.execute(
        "INSERT INTO turn_extension_snapshots ("
        + _COLUMNS
        + ", snapshot_digest, payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (*key, snapshot.digest, Jsonb(snapshot.model_dump(mode="json"))),
    )
    row = connection.execute(
        "SELECT snapshot_digest, payload FROM turn_extension_snapshots WHERE " + _KEY,
        key,
    ).fetchone()
    if row is None:
        raise ExtensionSnapshotIntegrityError("snapshot key collision or identity drift")
    stored = _decode_snapshot(row, scope, snapshot.session_id, snapshot.turn_id)
    if stored != snapshot or stored.digest != snapshot.digest:
        raise ExtensionSnapshotConflictError("turn already has a different snapshot")


def load_extension_snapshot_in_transaction(
    connection: Any,
    deployment_namespace: str,
    *,
    scope: ExtensionScope,
    session_id: str,
    turn_id: str,
    expected_digest: str,
) -> ExtensionSnapshot | None:
    scope = _validate_scope(scope)
    session_id = _ID.validate_python(session_id)
    turn_id = _ID.validate_python(turn_id)
    expected_digest = _DIGEST.validate_python(expected_digest)
    key = _snapshot_key(deployment_namespace, scope, session_id, turn_id)
    row = connection.execute(
        "SELECT snapshot_digest, payload FROM turn_extension_snapshots WHERE " + _KEY,
        key,
    ).fetchone()
    if row is None:
        return None
    snapshot = _decode_snapshot(row, scope, session_id, turn_id)
    if snapshot.digest != expected_digest:
        raise ExtensionSnapshotIntegrityError("snapshot disagrees with trusted digest")
    return snapshot


def resolve_extension_task_ceiling_in_transaction(
    connection: Any,
    deployment_namespace: str,
    session_id: str,
) -> ExtensionTaskCeiling:
    """Resolve an internal Segment to its root Task, binding, and Skill ceiling."""

    row = connection.execute(
        """
        SELECT segment.task_id, binding.binding_digest, binding.snapshot_json,
               workspace.skill_components
        FROM execution_segments AS segment
        JOIN task_binding_snapshots AS binding
          ON binding.deployment_namespace = segment.deployment_namespace
         AND binding.task_id = segment.task_id
         AND binding.binding_revision = (
             SELECT max(candidate.binding_revision)
             FROM task_binding_snapshots AS candidate
             WHERE candidate.deployment_namespace = segment.deployment_namespace
               AND candidate.task_id = segment.task_id
         )
        JOIN workspace_projections AS workspace
          ON workspace.deployment_namespace = segment.deployment_namespace
         AND workspace.session_id = segment.task_id
        WHERE segment.deployment_namespace = %s AND segment.session_id = %s
        FOR SHARE OF segment, binding, workspace
        """,
        (deployment_namespace, session_id),
    ).fetchone()
    if row is None:
        raise ValueError("extension admission Task authority was not found")
    binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
    if binding.binding_digest != row["binding_digest"]:
        raise ValueError("extension admission Task binding is corrupt")
    return ExtensionTaskCeiling(
        task_id=str(row["task_id"]),
        binding=binding,
        skill_components=tuple(row["skill_components"] or ()),
    )
