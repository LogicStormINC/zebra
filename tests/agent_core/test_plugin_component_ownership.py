"""Saved component facts cannot acquire independent authority through legacy selection."""

import asyncio
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_core.application.plugin_component_ownership import (
    managed_plugin_skill,
    managed_skill_ids,
    plugin_skill_identifier,
    plugin_skill_key,
)
from agent_core.application.plugin_installations import PluginInstallationService
from agent_core.application.plugin_resolution import PluginResolver
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.extensions import PluginSkillOrigin
from agent_core.domain.plugin_authority import PluginSelectionRefused
from agent_core.domain.plugin_installations import PluginInstallation
from agent_core.domain.plugin_packages import PluginPackageManifest, plugin_package_digest
from agent_core.domain.plugin_snapshots import ExtensionSelection
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_core.ports.plugin_installations import PluginInstallationPage

from tests.agent_storage.test_postgres_plugin_installations import _catalog, _record
from tests.agent_tools.test_cloud_skills import Backend


def skill_plugin(*, legacy=False, managed=True, enabled=True):
    """Use already saved Skill bytes; no provider or network client is composed."""
    backend = Backend()
    manifest = PluginPackageManifest.model_validate({
        "id": "test-plugin", "version": "1.0.0", "publisher": "Test",
        "components": [{"id": "guide", "kind": "skill-bundle", "skill_root": "skills/guide"}],
    })
    canonical = manifest.canonical_json()
    files = tuple(file.model_copy(update={"path": "skills/guide/" + file.path})
                  for file in backend.publication.manifest)
    package = _record().package.model_dump() | {
        "manifest": manifest, "canonical_manifest": canonical, "files": files,
        "manifest_digest": "sha256:" + sha256(canonical.encode()).hexdigest(),
        "package_digest": plugin_package_digest(
            canonical, ((file.path, file.size, file.sha256) for file in files)
        ),
    }
    if managed:
        backend.installation = backend.installation.model_copy(update={
            "installation_id": plugin_skill_identifier(package["package_digest"], "guide"),
            "plugin_origin": None if legacy else PluginSkillOrigin(
                package_digest=package["package_digest"], component_id="guide"
            ),
        })
    record = PluginInstallation.model_validate(_record().model_dump() | {
        "scope": backend.installation.scope, "package": package, "enabled": enabled,
        "bindings": [{"component_id": "guide", "kind": "skill-bundle",
                      "installation": backend.installation}],
    })
    return backend, record


def test_default_origin_preserves_legacy_digests_and_exact_id_proves_old_origin():
    backend, record = skill_plugin(legacy=True, enabled=False)
    skill = backend.installation
    assert "plugin_origin" not in skill.model_dump(mode="json")
    snapshot = ExtensionSnapshot(scope=skill.scope, session_id="session", turn_id="turn",
                                 skills=(skill,))
    assert ExtensionSnapshot.model_validate(snapshot.model_dump()).digest == snapshot.digest
    assert managed_plugin_skill(record, record.bindings[0])
    _, shared = skill_plugin(managed=False)
    assert not managed_plugin_skill(shared, shared.bindings[0])


def test_legacy_origin_survives_rebinding_and_scoped_catalog_is_fail_closed():
    async def check():
        backend, original = skill_plugin(legacy=True, enabled=False)
        _, rebound = skill_plugin(managed=False, enabled=False)
        rebound = rebound.model_copy(update={"revision": 3})
        store = AsyncMock()
        store.list.return_value = PluginInstallationPage(items=(rebound,))
        store.get_creation.return_value = original
        assert await managed_skill_ids(store, original.scope, (backend.installation,)) == {
            backend.installation.installation_id
        }
        store.get_creation.return_value = original.model_copy(update={
            "scope": original.scope.model_copy(update={"workspace_id": "foreign"})
        })
        with pytest.raises(ValueError, match="foreign"):
            await managed_skill_ids(store, original.scope, (backend.installation,))
    asyncio.run(check())


@pytest.mark.parametrize("legacy", [False, True])
def test_managed_skill_requires_enabled_plugin_and_shared_skill_remains_independent(legacy):
    async def check():
        backend, record = skill_plugin(legacy=legacy)
        installations, extensions, packages = AsyncMock(), AsyncMock(), AsyncMock()
        installations.get.return_value = record
        installations.list.return_value = PluginInstallationPage(items=(record,))
        extensions.get_skill.return_value = backend.installation
        extensions.get_skill_publication.return_value = backend.publication
        resolver = PluginResolver(installations, extensions, None, packages)
        ceiling = SimpleNamespace(skill_components=(backend.installation.version.skill_id,),
            binding=SimpleNamespace(effective_capabilities={"agent.execute"}),
            tool_profile="general", network_profile="full-gateway")
        arguments = dict(scope=record.scope, ceiling=ceiling, session_id="session", turn_id="turn")
        with pytest.raises(PluginSelectionRefused, match="origin"):
            await resolver.resolve(**arguments, selection=ExtensionSelection(
                skills=(backend.installation.installation_id,)))
        chosen = ExtensionSelection.model_validate({"plugins": [{
            "installation_id": record.installation_id, "revision": record.revision,
        }]})
        snapshot = await resolver.resolve(**arguments, selection=chosen)
        assert snapshot.plugins and snapshot.skills == (backend.installation,)
        assert not snapshot.direct_skills
        installations.get.return_value = record.model_copy(update={"enabled": False})
        with pytest.raises(PluginSelectionRefused, match="revision"):
            await resolver.resolve(**arguments, selection=chosen)
        shared_backend, shared = skill_plugin(managed=False, enabled=False)
        installations.list.return_value = PluginInstallationPage(items=(shared,))
        extensions.get_skill.return_value = shared_backend.installation
        result = await resolver.resolve(**arguments, selection=ExtensionSelection(
            skills=(shared_backend.installation.installation_id,)))
        assert not result.plugins and result.direct_skills == ("sample",)
    asyncio.run(check())


def test_origin_is_internal_exact_and_replay_cannot_strip_it():
    async def check():
        backend, record = skill_plugin()
        origin = backend.installation.plugin_origin
        extensions = AsyncMock()
        extensions.get_skill_creation.side_effect = ExtensionNotFoundError
        extensions.get_skill_publication.return_value = backend.publication
        args = dict(store=extensions, scope=record.scope,
            idempotency_key=plugin_skill_key(origin.package_digest, origin.component_id),
            payload={"skill_id": backend.installation.version.skill_id,
                     "version_id": backend.installation.version.version_id})
        created, fresh = await create_skill_installation(**args, plugin_origin=origin)
        assert fresh and created.plugin_origin == origin
        extensions.get_skill_creation.side_effect = None
        extensions.get_skill_creation.return_value = created
        extensions.get_skill.return_value = created
        replayed, fresh = await create_skill_installation(**args, plugin_origin=origin)
        assert not fresh and replayed == created
        with pytest.raises(ExtensionRevisionConflictError, match="origin"):
            await create_skill_installation(**args)
        with pytest.raises(ValueError, match="origin"):
            await create_skill_installation(**(args | {"idempotency_key": "wrong"}),
                                            plugin_origin=origin)
        with pytest.raises(ValueError):
            await create_skill_installation(**(args | {"payload": args["payload"] | {
                "plugin_origin": origin.model_dump()}}))
    asyncio.run(check())


def test_enable_freshly_checks_mcp_configuration_catalog_and_runtime():
    async def check():
        record = _record()
        catalog = _catalog(record.bindings[0].connection)
        record = record.model_copy(update={"bindings": (record.bindings[0].model_copy(
            update={"catalog_digest": catalog.digest}),)})
        store, extensions, catalogs, publisher = (AsyncMock() for _ in range(4))
        store.get.return_value = record
        extensions.get_mcp.return_value = record.bindings[0].connection
        catalogs.latest.return_value = catalog
        service = PluginInstallationService(store, extensions, catalogs, publisher, "cloud-a",
                                            mcp_available=False)
        args = dict(scope=record.scope, operated_by="operator", installation_id="plugin-a",
                    expected_revision=1, payload={"enabled": True})
        assert await service.readiness(record) == "mcp_runtime_unavailable"
        with pytest.raises(ExtensionRevisionConflictError, match="mcp_runtime"):
            await service.update(**args)
        assert not extensions.mock_calls and not store.save.mock_calls
        service = PluginInstallationService(store, extensions, catalogs, publisher, "cloud-a")
        assert await service.readiness(record) == "ready"
        for changes in ({"enabled": False}, {"revision": 2}):
            extensions.get_mcp.return_value = record.bindings[0].connection.model_copy(
                update=changes)
            with pytest.raises(ExtensionRevisionConflictError, match="component"):
                await service.update(**args)
        store.save.assert_not_awaited()
    asyncio.run(check())


def test_skill_version_update_retains_durable_managed_origin():
    from agent_core.application.extension_configuration import update_skill_version

    async def check():
        backend, record = skill_plugin()
        extensions = AsyncMock()
        extensions.get_skill.return_value = backend.installation
        version = backend.installation.version.model_copy(update={"version_id": "next"})
        extensions.get_skill_publication.return_value = backend.publication.model_copy(
            update={"version": version})
        changed = await update_skill_version(store=extensions, scope=record.scope,
            object_id=backend.installation.installation_id, expected_revision=1,
            payload={"skill_id": version.skill_id, "version_id": "next"})
        assert changed.plugin_origin == backend.installation.plugin_origin
        assert changed.version == version and changed.revision == 2
    asyncio.run(check())
