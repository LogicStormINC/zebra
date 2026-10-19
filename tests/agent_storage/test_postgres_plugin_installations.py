"""Plugin configuration proof against an exclusively disposable PostgreSQL schema."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectReceipt
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.domain.plugin_packages import PluginPackageManifest
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionRevisionConflictError,
)

from tests.agent_storage.test_postgres_extensions import SCOPE, dsn, postgres_dsn

__all__ = ["dsn", "postgres_dsn"]


def _catalog(connection: Any) -> McpToolCatalog:
    return McpToolCatalog(
        connection=connection,
        protocol_version="2025-03-26",
        tools=(McpCatalogTool(name="test", input_schema_json='{"type":"object"}'),),
    )


def _record(**updates: Any) -> Any:
    from agent_core.domain.plugin_installations import PluginInstallation

    manifest = PluginPackageManifest.model_validate(
        {
            "id": "test-plugin",
            "version": "1.0.0",
            "publisher": "Test",
            "components": [{"id": "test-mcp", "kind": "mcp-http", "connection_slot": "test-mcp"}],
        }
    )
    canonical = manifest.canonical_json()
    package_digest = (
        "sha256:"
        + sha256(
            json.dumps(
                {"manifest": json.loads(canonical), "files": []},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    expectation = ArtifactObjectExpectation(
        deployment_namespace="cloud-a",
        artifact_id=ArtifactId(uuid4()),
        sha256="a" * 64,
        size_bytes=2,
    )
    return PluginInstallation.model_validate(
        {
            "scope": SCOPE,
            "installation_id": "plugin-a",
            "revision": 1,
            "operated_by": "operator-a",
            "operated_at": datetime.now(UTC),
            "creation_key_digest": "a" * 64,
            "creation_request_digest": "b" * 64,
            "package": {
                "manifest": manifest,
                "canonical_manifest": canonical,
                "manifest_digest": "sha256:" + sha256(canonical.encode()).hexdigest(),
                "package_digest": package_digest,
                "files": [],
                "expectation": expectation,
                "receipt": ArtifactObjectReceipt(
                    expectation=expectation,
                    object_version="fixed-v1",
                    verified_at=datetime.now(UTC),
                ),
            },
            "bindings": [
                {
                    "component_id": "test-mcp",
                    "kind": "mcp-http",
                    "catalog_digest": "b" * 64,
                    "connection": {
                        "scope": SCOPE,
                        "connection_id": "connection-a",
                        "revision": 1,
                        "endpoint": "https://mcp.example/api",
                    },
                }
            ],
            **updates,
        }
    )


def test_plugin_scoped_cas_and_immutable_revision_recovery(dsn: str) -> None:
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

    store = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")
    fresh = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        original = _record()
        assert not original.enabled
        await store.save(scope=SCOPE, installation=original, expected_revision=None)
        changed = original.model_copy(update={"revision": 2})
        await fresh.save(scope=SCOPE, installation=changed, expected_revision=1)
        assert await store.get(scope=SCOPE, installation_id="plugin-a") == changed
        assert await fresh.get_creation(scope=SCOPE, installation_id="plugin-a") == original
        assert (
            await fresh.get_revision(
                scope=SCOPE,
                installation_id="plugin-a",
                revision=1,
            )
            == original
        )
        page = await fresh.list(scope=SCOPE, page=ExtensionPageRequest(limit=1))
        assert page.items == (changed,)
        for scope in (SCOPE, SCOPE.model_copy(update={"principal_id": "other"})):
            with pytest.raises(ExtensionNotFoundError):
                await fresh.get_revision(scope=scope, installation_id="plugin-a", revision=99)
        with pytest.raises(ExtensionNotFoundError):
            await fresh.get_revision(
                scope=SCOPE.model_copy(update={"workspace_id": "other"}),
                installation_id="plugin-a",
                revision=1,
            )
        other = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-b")
        with pytest.raises(ExtensionNotFoundError):
            await other.get(scope=SCOPE, installation_id="plugin-a")
        with pytest.raises(ExtensionRevisionConflictError):
            await store.save(scope=SCOPE, installation=changed, expected_revision=1)
        with pytest.raises(ValueError):
            await fresh.get_revision(scope=SCOPE, installation_id="plugin-a", revision=True)

    asyncio.run(check())


def test_enabled_plugin_requires_current_ready_bindings_but_disable_does_not(dsn: str) -> None:
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

    store = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        original = _record()
        await store.save(scope=SCOPE, installation=original, expected_revision=None)
        with pytest.raises(ExtensionRevisionConflictError):
            await store.save(
                scope=SCOPE,
                installation=original.model_copy(update={"revision": 2, "enabled": True}),
                expected_revision=1,
            )
        assert await store.get(scope=SCOPE, installation_id="plugin-a") == original
        await store.save(
            scope=SCOPE,
            installation=original.model_copy(update={"revision": 2}),
            expected_revision=1,
        )

    asyncio.run(check())


def test_enable_ready_mcp_then_disable_after_connection_changes(dsn: str) -> None:
    from agent_storage.postgres.extensions import PostgresExtensionStore
    from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

    store = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")
    components = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    catalogs = PostgresMcpCatalogStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        original = _record()
        binding = original.bindings[0]
        catalog = _catalog(binding.connection)
        original = type(original).model_validate(
            {
                **original.model_dump(),
                "bindings": [{**binding.model_dump(), "catalog_digest": catalog.digest}],
            }
        )
        await components.save_mcp(
            scope=SCOPE, connection=binding.connection, expected_revision=None
        )
        await catalogs.publish(scope=SCOPE, catalog=catalog)
        await store.save(scope=SCOPE, installation=original, expected_revision=None)
        enabled = original.model_copy(update={"revision": 2, "enabled": True})
        await store.save(scope=SCOPE, installation=enabled, expected_revision=1)
        await components.save_mcp(
            scope=SCOPE,
            connection=binding.connection.model_copy(update={"revision": 2, "enabled": False}),
            expected_revision=1,
        )
        with pytest.raises(ExtensionRevisionConflictError, match="binding changed"):
            await store.save(
                scope=SCOPE,
                installation=enabled.model_copy(update={"revision": 3}),
                expected_revision=2,
            )
        disabled = enabled.model_copy(update={"revision": 3, "enabled": False})
        await store.save(scope=SCOPE, installation=disabled, expected_revision=2)
        assert await store.get(scope=SCOPE, installation_id="plugin-a") == disabled
        assert (
            await store.get_revision(scope=SCOPE, installation_id="plugin-a", revision=2) == enabled
        )

    asyncio.run(check())


def test_enable_holds_component_lock_until_plugin_commit(dsn: str) -> None:
    from agent_storage.postgres.extensions import PostgresExtensionStore
    from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

    locked = threading.Event()
    release = threading.Event()

    class PausingStore(PostgresPluginInstallationStore):
        def _validate_mcp(self, transaction: Any, scope: Any, binding: Any) -> None:
            super()._validate_mcp(transaction, scope, binding)
            locked.set()
            assert release.wait(5), "test did not release plugin transaction"

    async def check() -> None:
        store = PausingStore(dsn, deployment_namespace="cloud-a")
        extensions = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
        catalogs = PostgresMcpCatalogStore(dsn, deployment_namespace="cloud-a")
        original = _record()
        binding = original.bindings[0]
        catalog = _catalog(binding.connection)
        original = type(original).model_validate(
            {
                **original.model_dump(),
                "bindings": [{**binding.model_dump(), "catalog_digest": catalog.digest}],
            }
        )
        await extensions.save_mcp(
            scope=SCOPE, connection=binding.connection, expected_revision=None
        )
        await catalogs.publish(scope=SCOPE, catalog=catalog)
        await store.save(scope=SCOPE, installation=original, expected_revision=None)
        enabling = asyncio.create_task(
            store.save(
                scope=SCOPE,
                installation=original.model_copy(update={"revision": 2, "enabled": True}),
                expected_revision=1,
            )
        )
        assert await asyncio.to_thread(locked.wait, 5)
        changing = asyncio.create_task(
            extensions.save_mcp(
                scope=SCOPE,
                connection=binding.connection.model_copy(update={"revision": 2}),
                expected_revision=1,
            )
        )
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(changing), timeout=0.15)
            assert not changing.done()
        finally:
            release.set()
            await asyncio.gather(enabling, changing)
        assert (await store.get(scope=SCOPE, installation_id="plugin-a")).enabled

    asyncio.run(check())


def test_empty_mcp_catalog_cannot_enable_plugin(dsn: str) -> None:
    from agent_storage.postgres.extensions import PostgresExtensionStore
    from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

    async def check() -> None:
        store = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")
        extensions = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
        catalogs = PostgresMcpCatalogStore(dsn, deployment_namespace="cloud-a")
        original = _record()
        binding = original.bindings[0]
        catalog = McpToolCatalog(connection=binding.connection, protocol_version="2025-03-26")
        original = type(original).model_validate(
            {
                **original.model_dump(),
                "bindings": [{**binding.model_dump(), "catalog_digest": catalog.digest}],
            }
        )
        await extensions.save_mcp(
            scope=SCOPE, connection=binding.connection, expected_revision=None
        )
        await catalogs.publish(scope=SCOPE, catalog=catalog)
        await store.save(scope=SCOPE, installation=original, expected_revision=None)
        with pytest.raises(ExtensionRevisionConflictError):
            await store.save(
                scope=SCOPE,
                installation=original.model_copy(update={"revision": 2, "enabled": True}),
                expected_revision=1,
            )

    asyncio.run(check())


def test_real_store_service_rebind_disables_and_replay_keeps_creation_intent(dsn: str) -> None:
    from unittest.mock import AsyncMock

    from agent_core.application.plugin_installations import PluginInstallationService
    from agent_storage.postgres.extensions import PostgresExtensionStore
    from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

    async def check() -> None:
        store = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")
        extensions = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
        catalogs = PostgresMcpCatalogStore(dsn, deployment_namespace="cloud-a")
        original = _record()
        connection = original.bindings[0].connection
        await extensions.save_mcp(scope=SCOPE, connection=connection, expected_revision=None)
        await catalogs.publish(scope=SCOPE, catalog=_catalog(connection))
        publisher = AsyncMock()
        publisher.publish.return_value = original.package
        service = PluginInstallationService(
            store=store,
            extensions=extensions,
            catalogs=catalogs,
            publisher=publisher,
            deployment_namespace="cloud-a",
        )
        payload = {
            "package_digest": original.package.package_digest,
            "bindings": [
                {
                    "kind": "mcp-http",
                    "component_id": "test-mcp",
                    "connection_id": connection.connection_id,
                }
            ],
        }
        created, fresh = await service.install(
            scope=SCOPE, operated_by="operator", idempotency_key="one", payload=payload
        )
        assert fresh and not created.enabled
        enabled = await service.update(
            scope=SCOPE,
            operated_by="operator",
            installation_id=created.installation_id,
            expected_revision=1,
            payload={"enabled": True},
        )
        assert enabled.enabled
        changed = connection.model_copy(
            update={"revision": 2, "endpoint": "https://mcp.example/changed"}
        )
        await extensions.save_mcp(scope=SCOPE, connection=changed, expected_revision=1)
        await catalogs.publish(scope=SCOPE, catalog=_catalog(changed))
        rebound = await service.update(
            scope=SCOPE,
            operated_by="operator",
            installation_id=created.installation_id,
            expected_revision=2,
            payload=payload,
        )
        assert not rebound.enabled and rebound.revision == 3
        assert rebound.bindings[0].connection == changed
        assert rebound.creation_request_digest == created.creation_request_digest
        assert (
            await store.get_revision(
                scope=SCOPE, installation_id=created.installation_id, revision=1
            )
            == created
        )
        replayed, fresh = await service.install(
            scope=SCOPE, operated_by="operator", idempotency_key="one", payload=payload
        )
        assert replayed == rebound and not fresh
        with pytest.raises(ExtensionRevisionConflictError):
            await service.install(
                scope=SCOPE,
                operated_by="operator",
                idempotency_key="one",
                payload={
                    **payload,
                    "bindings": [{**payload["bindings"][0], "connection_id": "different"}],
                },
            )
        with pytest.raises(ValueError):
            await store.save(
                scope=SCOPE,
                installation=rebound.model_copy(
                    update={
                        "revision": 4,
                        "creation_request_digest": "0" * 64,
                    }
                ),
                expected_revision=3,
            )
        assert await store.get(scope=SCOPE, installation_id=created.installation_id) == rebound

    asyncio.run(check())


def test_skill_binding_requires_exact_ready_publication_file_index(dsn: str) -> None:
    from agent_core.domain.extensions import SkillInstallation, SkillVersion
    from agent_core.domain.plugin_installations import PluginInstallation
    from agent_core.domain.plugin_packages import plugin_package_digest
    from agent_core.domain.skill_publications import (
        SkillPublication,
        SkillPublicationFile,
        publication_identity,
    )
    from agent_storage.postgres.extensions import PostgresExtensionStore
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore
    from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore

    async def check() -> None:
        publication_store = PostgresSkillPublicationStore(dsn, deployment_namespace="cloud-a")
        store = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")
        extensions = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
        skill_id, version_id, artifact_id = publication_identity(
            "cloud-a", SCOPE, "example", "1.0.0"
        )
        version = SkillVersion(
            skill_id=skill_id,
            version_id=version_id,
            artifact_ref=f"artifact://{artifact_id}",
            content_digest="c" * 64,
        )
        file = SkillPublicationFile(path="SKILL.md", size=7, sha256="d" * 64)
        publication = SkillPublication(
            scope=SCOPE,
            version=version,
            name="example",
            description="test",
            version_label="1.0.0",
            manifest=(file,),
            expectation=ArtifactObjectExpectation(
                deployment_namespace="cloud-a",
                artifact_id=artifact_id,
                sha256="e" * 64,
                size_bytes=9,
            ),
        )
        await publication_store.reserve(scope=SCOPE, publication=publication)
        skill = SkillInstallation(
            scope=SCOPE, installation_id="skill-a", revision=1, version=version
        )
        await extensions.save_skill(scope=SCOPE, installation=skill, expected_revision=None)
        package = _record().package.model_dump()
        manifest = PluginPackageManifest.model_validate(
            {
                "id": "test-plugin",
                "version": "1.0.0",
                "publisher": "Test",
                "components": [
                    {"id": "skill-one", "kind": "skill-bundle", "skill_root": "skills/one"}
                ],
            }
        )
        canonical = manifest.canonical_json()
        files = (file.model_copy(update={"path": "skills/one/SKILL.md"}),)
        package.update(
            manifest=manifest,
            canonical_manifest=canonical,
            files=files,
            manifest_digest="sha256:" + sha256(canonical.encode()).hexdigest(),
            package_digest=plugin_package_digest(
                canonical, ((file.path, file.size, file.sha256) for file in files)
            ),
        )
        original = PluginInstallation.model_validate(
            {
                **_record().model_dump(),
                "package": package,
                "bindings": [
                    {"component_id": "skill-one", "kind": "skill-bundle", "installation": skill}
                ],
            }
        )
        await store.save(scope=SCOPE, installation=original, expected_revision=None)
        enabled = original.model_copy(update={"revision": 2, "enabled": True})
        with pytest.raises(ExtensionRevisionConflictError, match="publication"):
            await store.save(scope=SCOPE, installation=enabled, expected_revision=1)
        await publication_store.mark_ready(
            scope=SCOPE,
            skill_id=skill_id,
            version_id=version_id,
            receipt=ArtifactObjectReceipt(
                expectation=publication.expectation,
                object_version="skill-v1",
                verified_at=datetime.now(UTC),
            ),
        )
        await store.save(scope=SCOPE, installation=enabled, expected_revision=1)
        assert await store.get(scope=SCOPE, installation_id="plugin-a") == enabled
        wrong_files = (files[0].model_copy(update={"sha256": "f" * 64}),)
        wrong_package = {
            **package,
            "files": wrong_files,
            "package_digest": plugin_package_digest(
                canonical, ((file.path, file.size, file.sha256) for file in wrong_files)
            ),
        }
        wrong = PluginInstallation.model_validate(
            {
                **original.model_dump(),
                "installation_id": "plugin-wrong",
                "package": wrong_package,
            }
        )
        await store.save(scope=SCOPE, installation=wrong, expected_revision=None)
        with pytest.raises(ExtensionRevisionConflictError, match="publication"):
            await store.save(
                scope=SCOPE,
                installation=wrong.model_copy(update={"revision": 2, "enabled": True}),
                expected_revision=1,
            )

    asyncio.run(check())
