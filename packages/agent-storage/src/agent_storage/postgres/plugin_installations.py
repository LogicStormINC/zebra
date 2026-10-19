"""Plugin persistence shares extension CAS transactions and locks bound revisions."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_core.domain.extensions import (
    ExtensionRevision,
    ExtensionScope,
    McpConnection,
    SkillInstallation,
)
from agent_core.domain.mcp_catalog import McpToolCatalog
from agent_core.domain.plugin_installations import (
    PluginInstallation,
    PluginMcpBinding,
    PluginSkillBinding,
)
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionRevisionConflictError,
)
from agent_core.ports.plugin_installations import PluginInstallationPage
from pydantic import TypeAdapter

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.extensions import (
    _CURRENT,
    _KEY,
    PostgresExtensionStore,
    _decode_record,
    _scope_key,
)
from agent_storage.postgres.skill_publications import _SCOPE as _PUBLICATION_SCOPE


class PostgresPluginInstallationStore(PostgresDatabase):
    def _extensions(self) -> PostgresExtensionStore:
        return PostgresExtensionStore(
            self._dsn,
            deployment_namespace=self.deployment_namespace,
            task_io_connections=self._task_io,
        )

    async def get(self, *, scope: ExtensionScope, installation_id: str) -> PluginInstallation:
        row = await asyncio.to_thread(self._extensions()._get, scope, "plugin", installation_id)
        return _decode_record(PluginInstallation, row, scope)

    async def get_current_batch(
        self,
        *,
        scope: ExtensionScope,
        installation_ids: tuple[str, ...],
    ) -> tuple[PluginInstallation, ...]:
        if not installation_ids:
            return ()
        if len(installation_ids) > 32 or len(set(installation_ids)) != len(installation_ids):
            raise ValueError("plugin lookup exceeds bounded unique identities")

        def load() -> tuple[PluginInstallation, ...]:
            from agent_storage.postgres.extensions import _SCOPE

            with self.connect() as connection:
                rows = connection.execute(
                    _CURRENT + _SCOPE + " AND object_id = ANY(%s) ORDER BY object_id "
                    "FOR SHARE OF extension_configurations",
                    (
                        *_scope_key(self.deployment_namespace, scope, "plugin"),
                        list(installation_ids),
                    ),
                ).fetchall()
                ready: list[PluginInstallation] = []
                for row in rows:
                    record = _decode_record(PluginInstallation, row, scope)
                    if not record.enabled:
                        continue
                    try:
                        self._validate_enabled(connection, scope, record, record.revision)
                    except ExtensionRevisionConflictError:
                        continue
                    ready.append(record)
            return tuple(ready)

        return await asyncio.to_thread(load)

    async def get_creation(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
    ) -> PluginInstallation:
        return await self.get_revision(scope=scope, installation_id=installation_id, revision=1)

    async def get_revision(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
        revision: int,
    ) -> PluginInstallation:
        TypeAdapter(ExtensionRevision).validate_python(revision)
        return await asyncio.to_thread(self._get_revision, scope, installation_id, revision)

    def _get_revision(
        self,
        scope: ExtensionScope,
        installation_id: str,
        revision: int,
    ) -> PluginInstallation:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT object_id, revision, payload FROM extension_configuration_revisions "
                "WHERE " + _KEY + " AND revision = %s",
                (
                    *_scope_key(self.deployment_namespace, scope, "plugin"),
                    installation_id,
                    revision,
                ),
            ).fetchone()
        if row is None:
            raise ExtensionNotFoundError("plugin revision not found in supplied scope")
        return _decode_record(PluginInstallation, row, scope)

    async def list(
        self,
        *,
        scope: ExtensionScope,
        page: ExtensionPageRequest,
    ) -> PluginInstallationPage:
        rows = await asyncio.to_thread(self._extensions()._list, scope, "plugin", page)
        return PluginInstallationPage(
            items=tuple(
                _decode_record(PluginInstallation, row, scope) for row in rows[: page.limit]
            ),
            next_cursor=rows[page.limit - 1]["object_id"] if len(rows) > page.limit else None,
        )

    async def save(
        self,
        *,
        scope: ExtensionScope,
        installation: PluginInstallation,
        expected_revision: int | None,
    ) -> None:
        record = PluginInstallation.model_validate(installation.model_dump())
        if record.package.expectation.deployment_namespace != self.deployment_namespace:
            raise ValueError("package belongs to another deployment")
        if expected_revision is None and record.enabled:
            raise ValueError("plugin installations must be created disabled")
        await asyncio.to_thread(
            self._extensions()._save,
            scope,
            "plugin",
            record,
            expected_revision,
            lambda transaction: self._validate_enabled(
                transaction, scope, record, expected_revision
            ),
        )

    def _validate_enabled(
        self,
        transaction: Any,
        scope: ExtensionScope,
        record: PluginInstallation,
        expected_revision: int | None,
    ) -> None:
        if expected_revision is None:
            return
        previous = transaction.execute(
            "SELECT object_id, revision, payload FROM extension_configuration_revisions "
            "WHERE " + _KEY + " AND revision = %s",
            (
                *_scope_key(self.deployment_namespace, scope, "plugin"),
                record.installation_id,
                expected_revision,
            ),
        ).fetchone()
        if previous is None:
            raise ExtensionRevisionConflictError("plugin creation must remain disabled")
        prior = _decode_record(PluginInstallation, previous, scope)
        if (
            prior.creation_key_digest != record.creation_key_digest
            or prior.creation_request_digest != record.creation_request_digest
        ):
            raise ValueError("plugin creation identity is immutable")
        if not record.enabled:
            return
        if prior.package != record.package or prior.bindings != record.bindings:
            raise ExtensionRevisionConflictError("package or binding changes must remain disabled")
        # ponytail: at most 32 rows; deterministic lock order avoids cross-plugin deadlocks.
        for binding in sorted(
            record.bindings,
            key=lambda item: (
                item.kind,
                item.installation.installation_id
                if isinstance(item, PluginSkillBinding)
                else item.connection.connection_id,
            ),
        ):
            expected = (
                binding.installation
                if isinstance(binding, PluginSkillBinding)
                else binding.connection
            )
            kind = "skill" if isinstance(binding, PluginSkillBinding) else "mcp"
            identifier = (
                binding.installation.installation_id
                if isinstance(binding, PluginSkillBinding)
                else binding.connection.connection_id
            )
            row = transaction.execute(
                _CURRENT + _KEY + " FOR SHARE OF extension_configurations",
                (*_scope_key(self.deployment_namespace, scope, kind), identifier),
            ).fetchone()
            if row is None or not expected.enabled:
                raise ExtensionRevisionConflictError("plugin component binding changed")
            current = (
                _decode_record(SkillInstallation, row, scope)
                if isinstance(binding, PluginSkillBinding)
                else _decode_record(McpConnection, row, scope)
            )
            if current != expected:
                raise ExtensionRevisionConflictError("plugin component binding changed")
            if isinstance(binding, PluginSkillBinding):
                self._validate_skill(transaction, scope, record, binding)
            else:
                self._validate_mcp(transaction, scope, binding)

    def _validate_skill(
        self,
        transaction: Any,
        scope: ExtensionScope,
        record: PluginInstallation,
        binding: PluginSkillBinding,
    ) -> None:
        version = binding.installation.version
        row = transaction.execute(
            "SELECT payload FROM skill_package_versions WHERE "
            + _PUBLICATION_SCOPE
            + " AND skill_id = %s AND version_id = %s FOR SHARE",
            (
                *_scope_key(self.deployment_namespace, scope, "skill")[:-1],
                version.skill_id,
                version.version_id,
            ),
        ).fetchone()
        if row is None:
            raise ExtensionRevisionConflictError("plugin Skill publication unavailable")
        publication = SkillPublication.model_validate(row["payload"])
        if (
            publication.scope != scope
            or publication.version != version
            or publication.state != "ready"
            or publication.manifest != record.package.skill_files(binding.component_id)
            or publication.expectation.deployment_namespace != self.deployment_namespace
        ):
            raise ExtensionRevisionConflictError("plugin Skill publication disagrees with package")

    def _validate_mcp(
        self,
        transaction: Any,
        scope: ExtensionScope,
        binding: PluginMcpBinding,
    ) -> None:
        expected = binding.connection
        if expected.auth_state.value not in {
            "not_required",
            "ready",
        } or expected.auth_mode.value not in {"none", "bearer"}:
            raise ExtensionRevisionConflictError("plugin MCP authentication unavailable")
        row = transaction.execute(
            "SELECT payload FROM mcp_catalog_versions WHERE "
            + _KEY
            + " AND revision = %s AND digest = %s FOR SHARE",
            (
                *_scope_key(self.deployment_namespace, scope, "mcp"),
                expected.connection_id,
                expected.revision,
                binding.catalog_digest,
            ),
        ).fetchone()
        if row is None:
            raise ExtensionRevisionConflictError("plugin MCP catalog unavailable")
        catalog = McpToolCatalog.model_validate(row["payload"])
        if (
            catalog.connection != expected
            or catalog.digest != binding.catalog_digest
            or not catalog.tools
        ):
            raise ExtensionRevisionConflictError("plugin MCP catalog disagrees with binding")
