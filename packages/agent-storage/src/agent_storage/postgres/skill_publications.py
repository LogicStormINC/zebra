"""Exact-scope metadata reservations; object payloads never enter PostgreSQL."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import Any

from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.skill_publications import (
    UPLOAD_IDEMPOTENCY_KEY,
    SkillPublicationConflictError,
    SkillPublicationNotFoundError,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase

_SCOPE = """scope_digest = %s AND deployment_namespace = %s
    AND authority_issuer = %s AND namespace_id = %s
    AND principal_id = %s AND workspace_id = %s"""
_KEY = _SCOPE + " AND skill_id = %s AND version_id = %s"
_COLUMNS = """scope_digest, deployment_namespace, authority_issuer, namespace_id,
    principal_id, workspace_id, skill_id, version_id, name, version_label, payload"""
_SELECT = "SELECT " + _COLUMNS + " FROM skill_package_versions WHERE " + _KEY


class PostgresSkillPublicationStore(PostgresDatabase):
    async def reserve(
        self, *, scope: ExtensionScope, publication: SkillPublication,
        idempotency_key: str | None = None,
    ) -> SkillPublication:
        if idempotency_key is not None:
            idempotency_key = UPLOAD_IDEMPOTENCY_KEY.validate_python(idempotency_key)
        publication = SkillPublication.model_validate(publication.model_dump())
        self._validate_scope(publication, scope)
        if publication.state != "publishing":
            raise ValueError("reservations must begin publishing without receipt")
        return await asyncio.to_thread(self._reserve, scope, publication, idempotency_key)

    async def get(
        self, *, scope: ExtensionScope, skill_id: str, version_id: str,
    ) -> SkillPublication:
        return await asyncio.to_thread(self._get, scope, skill_id, version_id)

    async def mark_ready(
        self, *, scope: ExtensionScope, skill_id: str, version_id: str,
        receipt: ArtifactObjectReceipt,
    ) -> SkillPublication:
        receipt = ArtifactObjectReceipt.model_validate(receipt.model_dump())
        if receipt.expectation.deployment_namespace != self.deployment_namespace:
            raise ValueError("receipt belongs to another deployment")
        return await asyncio.to_thread(self._mark_ready, scope, skill_id, version_id, receipt)

    def _scope(self, scope: ExtensionScope) -> tuple[str, ...]:
        scope = ExtensionScope.model_validate(scope.model_dump())
        coordinates = (self.deployment_namespace, scope.authority_issuer, scope.namespace_id,
                       scope.principal_id, scope.workspace_id)
        # ponytail: compact indexes avoid B-tree limits; all raw coordinates
        # remain mandatory predicates, so the digest is never authorization.
        digest = sha256(json.dumps(coordinates, ensure_ascii=True).encode()).hexdigest()
        return (digest, *coordinates)

    def _validate_scope(self, publication: SkillPublication, scope: ExtensionScope) -> None:
        if (publication.scope != scope
                or publication.expectation.deployment_namespace != self.deployment_namespace):
            raise ValueError("publication disagrees with trusted storage scope")

    def _decode(
        self, row: dict[str, Any], scope: ExtensionScope, skill_id: str, version_id: str,
    ) -> SkillPublication:
        record = SkillPublication.model_validate(row["payload"])
        self._validate_scope(record, scope)
        if (tuple(row[field] for field in (
                "scope_digest", "deployment_namespace", "authority_issuer", "namespace_id",
                "principal_id", "workspace_id")) != self._scope(scope)
                or row["skill_id"] != skill_id or record.version.skill_id != skill_id
                or row["version_id"] != version_id or record.version.version_id != version_id
                or row["name"] != record.name or row["version_label"] != record.version_label):
            raise ValueError("publication payload disagrees with storage coordinates")
        return record

    def _get(self, scope: ExtensionScope, skill_id: str, version_id: str) -> SkillPublication:
        with self.connect() as connection:
            row = connection.execute(
                _SELECT, (*self._scope(scope), skill_id, version_id),
            ).fetchone()
        if row is None:
            raise SkillPublicationNotFoundError("publication not found in supplied scope")
        return self._decode(row, scope, skill_id, version_id)

    def _reserve(
        self, scope: ExtensionScope, publication: SkillPublication, idempotency_key: str | None,
    ) -> SkillPublication:
        skill_id, version_id = publication.version.skill_id, publication.version.version_id
        key = (*self._scope(scope), skill_id, version_id)
        with self.connect() as connection:
            if idempotency_key is not None:
                self._reserve_upload_key(connection, scope, publication, idempotency_key)
            connection.execute(
                "INSERT INTO skill_package_versions (" + _COLUMNS + ") "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (*key, publication.name, publication.version_label,
                 Jsonb(publication.model_dump(mode="json"))),
            )
            row = connection.execute(_SELECT + " FOR UPDATE", key).fetchone()
            if row is None:
                raise SkillPublicationConflictError("publication coordinates already reserved")
            current = self._decode(row, scope, skill_id, version_id)
            if not current.same_candidate(publication):
                raise SkillPublicationConflictError("named version reserves different bytes")
            return current

    def _reserve_upload_key(
        self, connection: Any, scope: ExtensionScope, publication: SkillPublication, key: str,
    ) -> None:
        coordinates = (*self._scope(scope), sha256(key.encode("ascii")).hexdigest())
        candidate = (publication.version.skill_id, publication.version.version_id,
                     publication.expectation.sha256, publication.expectation.size_bytes)
        connection.execute(
            "INSERT INTO skill_package_upload_keys (scope_digest, deployment_namespace, "
            "authority_issuer, namespace_id, principal_id, workspace_id, key_digest, "
            "skill_id, version_id, archive_sha256, archive_size) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (*coordinates, *candidate),
        )
        row = connection.execute(
            "SELECT skill_id, version_id, archive_sha256, archive_size "
            "FROM skill_package_upload_keys WHERE " + _SCOPE + " AND key_digest = %s FOR UPDATE",
            coordinates,
        ).fetchone()
        if row is None or tuple(row[field] for field in (
            "skill_id", "version_id", "archive_sha256", "archive_size",
        )) != candidate:
            raise SkillPublicationConflictError("upload key reserves a different package")

    def _mark_ready(
        self, scope: ExtensionScope, skill_id: str, version_id: str, receipt: ArtifactObjectReceipt,
    ) -> SkillPublication:
        key = (*self._scope(scope), skill_id, version_id)
        with self.connect() as connection:
            row = connection.execute(_SELECT + " FOR UPDATE", key).fetchone()
            if row is None:
                raise SkillPublicationNotFoundError("publication not found in supplied scope")
            current = self._decode(row, scope, skill_id, version_id)
            if receipt.expectation != current.expectation:
                raise ValueError("receipt disagrees with reserved object")
            if current.state == "ready":
                if (current.receipt is None
                        or current.receipt.object_version != receipt.object_version):
                    raise ValueError("receipt disagrees with ready object version")
                return current
            ready = SkillPublication.model_validate({
                **current.model_dump(), "state": "ready", "receipt": receipt,
            })
            connection.execute(
                "UPDATE skill_package_versions SET payload = %s WHERE " + _KEY,
                (Jsonb(ready.model_dump(mode="json")), *key),
            )
            return ready
