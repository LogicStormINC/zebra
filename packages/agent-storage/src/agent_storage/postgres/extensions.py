"""Exact-scope extension persistence; each threaded operation owns its transaction."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import Any, Literal

from agent_core.domain.extensions import ExtensionScope, McpConnection, SkillInstallation
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.extensions import (
    AuthorizedSkill,
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionRevisionConflictError,
    ExtensionSkillAuthorizationError,
    ExtensionSkillConflictError,
    McpConnectionPage,
    SkillInstallationPage,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore

_SCOPE = """scope_digest = %s AND deployment_namespace = %s
    AND authority_issuer = %s AND namespace_id = %s
    AND principal_id = %s AND workspace_id = %s AND kind = %s"""
_KEY = _SCOPE + " AND object_id = %s"
_COLUMNS = """scope_digest, deployment_namespace, authority_issuer, namespace_id,
    principal_id, workspace_id, kind, object_id"""
_CURRENT = """SELECT object_id, revision, payload FROM extension_configurations
    JOIN extension_configuration_revisions USING
    (scope_digest, deployment_namespace, authority_issuer, namespace_id, principal_id,
     workspace_id, kind, object_id, revision) WHERE """


class ExtensionSnapshotAdmissionConflictError(RuntimeError):
    """Selected configuration changed before its command could commit."""


def _scope_key(
    deployment_namespace: str,
    scope: ExtensionScope,
    kind: str,
) -> tuple[str, ...]:
    scope = ExtensionScope.model_validate(scope.model_dump())
    coordinates = (
        deployment_namespace,
        scope.authority_issuer,
        scope.namespace_id,
        scope.principal_id,
        scope.workspace_id,
    )
    # ponytail: compact index keys avoid PostgreSQL's B-tree entry ceiling;
    # every query still compares the original scope, so the digest is not authority.
    digest = sha256(json.dumps(coordinates, ensure_ascii=True).encode()).hexdigest()
    return (digest, *coordinates, kind)


def _skill_lock_key(
    deployment_namespace: str,
    scope: ExtensionScope,
    skill_id: str,
) -> str:
    """Opaque advisory key for one Skill within one complete exact scope."""
    scope_digest = _scope_key(deployment_namespace, scope, "skill")[0]
    return sha256(json.dumps((scope_digest, skill_id), ensure_ascii=True).encode()).hexdigest()


def _decode_record[T: (SkillInstallation, McpConnection)](
    model: type[T],
    row: dict[str, Any],
    scope: ExtensionScope,
) -> T:
    record = model.model_validate(row["payload"])
    identifier = (
        record.installation_id if isinstance(record, SkillInstallation) else record.connection_id
    )
    if (
        record.scope != scope
        or identifier != row["object_id"]
        or record.revision != row["revision"]
    ):
        raise ValueError("extension payload disagrees with its storage coordinates")
    return record


class PostgresExtensionStore(PostgresDatabase):
    """Configuration only: credential references are persisted, never resolved here."""

    async def get_skill(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
    ) -> SkillInstallation:
        row = await asyncio.to_thread(self._get, scope, "skill", installation_id)
        return self._decode(SkillInstallation, row, scope)

    async def authorize_frozen_skills(
        self,
        *,
        scope: ExtensionScope,
        installations: tuple[SkillInstallation, ...],
    ) -> tuple[AuthorizedSkill, ...]:
        validated = tuple(
            SkillInstallation.model_validate(item.model_dump()) for item in installations
        )
        return await asyncio.to_thread(self._authorize_frozen_skills, scope, validated)

    def _authorize_frozen_skills(
        self,
        scope: ExtensionScope,
        installations: tuple[SkillInstallation, ...],
    ) -> tuple[AuthorizedSkill, ...]:
        if len(installations) > 32:
            raise ExtensionSkillAuthorizationError("frozen Skill selection exceeds limit")
        identifiers = tuple(item.installation_id for item in installations)
        if len(identifiers) != len(set(identifiers)):
            raise ExtensionSkillAuthorizationError("frozen Skill selection is ambiguous")
        if not installations:
            return ()
        requested = [
            {
                "ordinal": ordinal,
                "installation_id": item.installation_id,
                "skill_id": item.version.skill_id,
                "version_id": item.version.version_id,
            }
            for ordinal, item in enumerate(installations)
        ]
        scope_key = self._scope(scope, "skill")
        with self.connect() as connection:
            rows = connection.execute(
                """WITH requested AS (
                    SELECT * FROM jsonb_to_recordset(%s::jsonb) AS r(
                        ordinal integer, installation_id text, skill_id text, version_id text)
                )
                SELECT r.ordinal, r.installation_id, c.object_id, c.revision,
                    cr.payload AS installation_payload, p.payload AS publication_payload
                FROM requested r
                LEFT JOIN extension_configurations c ON
                    c.scope_digest = %s AND c.deployment_namespace = %s
                    AND c.authority_issuer = %s AND c.namespace_id = %s
                    AND c.principal_id = %s AND c.workspace_id = %s
                    AND c.kind = %s AND c.object_id = r.installation_id
                LEFT JOIN extension_configuration_revisions cr USING
                    (scope_digest, deployment_namespace, authority_issuer, namespace_id,
                     principal_id, workspace_id, kind, object_id, revision)
                LEFT JOIN skill_package_versions p ON
                    p.scope_digest = c.scope_digest
                    AND p.deployment_namespace = c.deployment_namespace
                    AND p.authority_issuer = c.authority_issuer
                    AND p.namespace_id = c.namespace_id
                    AND p.principal_id = c.principal_id
                    AND p.workspace_id = c.workspace_id
                    AND p.skill_id = r.skill_id AND p.version_id = r.version_id
                ORDER BY r.ordinal""",
                (Jsonb(requested), *scope_key),
            ).fetchall()
        if len(rows) != len(installations):
            raise ExtensionSkillAuthorizationError("frozen Skill selection is unavailable")
        authorized: list[AuthorizedSkill] = []
        try:
            for expected, row in zip(installations, rows, strict=True):
                if row["object_id"] is None or row["publication_payload"] is None:
                    raise ValueError
                current = _decode_record(
                    SkillInstallation,
                    {
                        "object_id": row["object_id"],
                        "revision": row["revision"],
                        "payload": row["installation_payload"],
                    },
                    scope,
                )
                publication = SkillPublication.model_validate(row["publication_payload"])
                if (
                    current != expected
                    or not current.enabled
                    or publication.scope != scope
                    or publication.version != expected.version
                    or publication.state != "ready"
                    or publication.receipt is None
                    or publication.expectation.deployment_namespace != self.deployment_namespace
                ):
                    raise ValueError
                authorized.append(AuthorizedSkill(current, publication))
        except (TypeError, ValueError):
            raise ExtensionSkillAuthorizationError("frozen Skill selection changed") from None
        return tuple(authorized)

    async def get_mcp(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
    ) -> McpConnection:
        row = await asyncio.to_thread(self._get, scope, "mcp", connection_id)
        return self._decode(McpConnection, row, scope)

    async def list_skills(
        self,
        *,
        scope: ExtensionScope,
        page: ExtensionPageRequest,
    ) -> SkillInstallationPage:
        rows = await asyncio.to_thread(self._list, scope, "skill", page)
        return SkillInstallationPage(
            items=tuple(self._decode(SkillInstallation, row, scope) for row in rows[: page.limit]),
            next_cursor=rows[page.limit - 1]["object_id"] if len(rows) > page.limit else None,
        )

    async def get_mcp_creation(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
    ) -> McpConnection:
        row = await asyncio.to_thread(self._get_creation, scope, "mcp", connection_id)
        return self._decode(McpConnection, row, scope)

    def _get_creation(self, scope: ExtensionScope, kind: str, identifier: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT object_id, revision, payload FROM extension_configuration_revisions "
                "WHERE " + _KEY + " AND revision = 1",
                (*self._scope(scope, kind), identifier),
            ).fetchone()
        if row is None:
            raise ExtensionNotFoundError("extension creation not found in supplied scope")
        return row

    async def list_mcp(
        self,
        *,
        scope: ExtensionScope,
        page: ExtensionPageRequest,
    ) -> McpConnectionPage:
        rows = await asyncio.to_thread(self._list, scope, "mcp", page)
        return McpConnectionPage(
            items=tuple(self._decode(McpConnection, row, scope) for row in rows[: page.limit]),
            next_cursor=rows[page.limit - 1]["object_id"] if len(rows) > page.limit else None,
        )

    async def save_skill(
        self,
        *,
        scope: ExtensionScope,
        installation: SkillInstallation,
        expected_revision: int | None,
    ) -> None:
        validated = SkillInstallation.model_validate(installation.model_dump())
        await asyncio.to_thread(self._save, scope, "skill", validated, expected_revision)

    async def save_mcp(
        self,
        *,
        scope: ExtensionScope,
        connection: McpConnection,
        expected_revision: int | None,
    ) -> None:
        validated = McpConnection.model_validate(connection.model_dump())
        await asyncio.to_thread(self._save, scope, "mcp", validated, expected_revision)

    def _scope(self, scope: ExtensionScope, kind: str) -> tuple[str, ...]:
        return _scope_key(self.deployment_namespace, scope, kind)

    @staticmethod
    def _decode[T: (SkillInstallation, McpConnection)](
        model: type[T],
        row: dict[str, Any],
        scope: ExtensionScope,
    ) -> T:
        return _decode_record(model, row, scope)

    def _get(self, scope: ExtensionScope, kind: str, identifier: str) -> dict[str, Any]:
        parameters = (*self._scope(scope, kind), identifier)
        with self.connect() as connection:
            row = connection.execute(_CURRENT + _KEY, parameters).fetchone()
        if row is None:
            raise ExtensionNotFoundError("extension not found in supplied scope")
        return row

    def _list(
        self,
        scope: ExtensionScope,
        kind: str,
        page: ExtensionPageRequest,
    ) -> list[dict[str, Any]]:
        page = ExtensionPageRequest.model_validate(page.model_dump())
        parameters = (*self._scope(scope, kind), page.cursor or "", page.limit + 1)
        with self.connect() as connection:
            return connection.execute(
                _CURRENT + _SCOPE + " AND object_id > %s ORDER BY object_id LIMIT %s",
                parameters,
            ).fetchall()

    def _save(
        self,
        scope: ExtensionScope,
        kind: Literal["skill", "mcp"],
        record: SkillInstallation | McpConnection,
        expected_revision: int | None,
    ) -> None:
        if record.scope != scope:
            raise ValueError("extension scope disagrees with supplied scope")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("expected revision must be a positive integer or None")
        if record.revision != (1 if expected_revision is None else expected_revision + 1):
            raise ValueError("extension revision must follow expected revision")
        identifier = (
            record.installation_id
            if isinstance(record, SkillInstallation)
            else record.connection_id
        )
        key = (*self._scope(scope, kind), identifier)
        with self.connect() as connection:
            if isinstance(record, SkillInstallation):
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 52))",
                    (_skill_lock_key(self.deployment_namespace, scope, record.version.skill_id),),
                )
                if record.enabled:
                    enabled = connection.execute(
                        _CURRENT + _SCOPE + " AND object_id <> %s AND payload->>'enabled' = 'true' "
                        "AND payload->'version'->>'skill_id' = %s LIMIT 1",
                        (
                            *self._scope(scope, kind),
                            identifier,
                            record.version.skill_id,
                        ),
                    ).fetchone()
                    if enabled is not None:
                        raise ExtensionSkillConflictError(
                            "another enabled installation already owns this Skill"
                        )
            if expected_revision is None:
                created = connection.execute(
                    "INSERT INTO extension_configurations (" + _COLUMNS + ", revision) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING RETURNING revision",
                    (*key, record.revision),
                ).fetchone()
                if created is None:
                    raise ExtensionRevisionConflictError("extension already exists")
            else:
                current = connection.execute(
                    "SELECT revision FROM extension_configurations WHERE " + _KEY + " FOR UPDATE",
                    key,
                ).fetchone()
                if current is None:
                    raise ExtensionNotFoundError("extension not found in supplied scope")
                if current["revision"] != expected_revision:
                    raise ExtensionRevisionConflictError("extension revision conflict")
                connection.execute(
                    "UPDATE extension_configurations SET revision = %s WHERE " + _KEY,
                    (record.revision, *key),
                )
            connection.execute(
                "INSERT INTO extension_configuration_revisions ("
                + _COLUMNS
                + ", revision, payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (*key, record.revision, Jsonb(record.model_dump(mode="json"))),
            )

    async def get_skill_publication(
        self,
        *,
        scope: ExtensionScope,
        skill_id: str,
        version_id: str,
    ) -> SkillPublication:
        return await PostgresSkillPublicationStore(
            self._dsn,
            deployment_namespace=self.deployment_namespace,
        ).get(scope=scope, skill_id=skill_id, version_id=version_id)

    async def get_skill_creation(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
    ) -> SkillInstallation:
        row = await asyncio.to_thread(self._get_creation, scope, "skill", installation_id)
        return self._decode(SkillInstallation, row, scope)


def validate_skill_snapshot_in_transaction(
    connection: Any,
    deployment_namespace: str,
    scope: ExtensionScope,
    installations: tuple[SkillInstallation, ...],
) -> None:
    """Lock and recheck selected revisions before the command transaction commits."""
    if not installations:
        return
    if len(installations) > 32:
        raise ExtensionSnapshotAdmissionConflictError(
            "selected Skill snapshot exceeds the admission bound"
        )
    identifiers = tuple(item.installation_id for item in installations)
    if len(identifiers) != len(set(identifiers)):
        raise ExtensionSnapshotAdmissionConflictError(
            "selected Skill installation identities are not unique"
        )
    rows = connection.execute(
        _CURRENT + _SCOPE + " AND object_id = ANY(%s) FOR SHARE OF extension_configurations",
        (*_scope_key(deployment_namespace, scope, "skill"), list(identifiers)),
    ).fetchall()
    current_by_id = {row["object_id"]: row for row in rows}
    if set(current_by_id) != set(identifiers):
        raise ExtensionSnapshotAdmissionConflictError(
            "selected Skill installation is no longer available"
        )
    for installation in installations:
        current = _decode_record(
            SkillInstallation, current_by_id[installation.installation_id], scope
        )
        if current != installation or not current.enabled:
            raise ExtensionSnapshotAdmissionConflictError(
                "selected Skill installation changed during admission"
            )
