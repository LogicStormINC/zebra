"""Ordinary AG-UI commands expose Plugin selection without altering official input."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from agent_core.application.plugin_resolution import PluginResolver
from agent_core.ports.extensions import SkillInstallationPage
from agent_core.ports.plugin_installations import PluginInstallationPage
from zebra_agent_api.ag_ui_command import AgUiCommandEnvelope, _command_payload
from zebra_agent_api.plugin_installations import _public

from tests.agent_core.test_plugin_component_ownership import skill_plugin
from tests.api.test_extension_turn_admission import _admission


def test_agui_selection_is_typed_outer_transport_and_preserves_explicit_empty():
    body = {"action": "run", "threadId": "thread", "runId": "run", "expectedRevision": 0,
            "input": {"messages": [{"id": "message", "role": "user", "content": "Explain"}]}}
    assert "extension_selection" not in _command_payload(AgUiCommandEnvelope(**body))
    for selected in ({}, {"plugins": [{"installation_id": "plugin-a", "revision": 2}]}):
        payload = _command_payload(AgUiCommandEnvelope(**body, extensionSelection=selected))
        assert payload["extension_selection"]["plugins"] == selected.get("plugins", [])
        assert "extensionSelection" not in payload["input"]
        assert "extension_selection" not in payload["input"]
        assert payload["input"]["messages"] == body["input"]["messages"]
    with pytest.raises(ValueError, match="stop"):
        _command_payload(AgUiCommandEnvelope(**(body | {"action": "stop", "input": None}),
                                            extensionSelection={}))
    with pytest.raises(ValueError):
        AgUiCommandEnvelope(**body, extensionSelection={"plugins": [{
            "installation_id": "plugin-a", "revision": True}]})


def test_managed_skill_can_enter_frozen_task_ceiling_but_legacy_turn_cannot_bypass_plugin():
    backend, record = skill_plugin(legacy=True, enabled=False)
    admission, extensions, _ = _admission()
    installations = AsyncMock()
    installations.list.return_value = PluginInstallationPage(items=(record,))
    admission._plugins = PluginResolver(installations, extensions, None, AsyncMock())
    extensions.list_skills.return_value = SkillInstallationPage(items=(backend.installation,))
    skill_ids = (backend.installation.version.skill_id,)
    assert admission._enabled_skills(record.scope, skill_ids, allow_managed=True) == [
        backend.installation
    ]
    assert admission._enabled_skills(record.scope, skill_ids) == []
    shared_backend, shared = skill_plugin(managed=False, enabled=False)
    installations.list.return_value = PluginInstallationPage(items=(shared,))
    extensions.list_skills.return_value = SkillInstallationPage(
        items=(shared_backend.installation,)
    )
    assert admission._enabled_skills(record.scope, skill_ids) == [shared_backend.installation]


def test_inventory_has_exact_skill_identity_origin_and_truthful_configured_readiness():
    backend, record = skill_plugin(legacy=True)
    public = _public(record, "ready")
    assert public["readiness"] == {"ready": True, "reason": "ready"}
    binding = public["bindings"][0]
    assert binding["skill_id"] == backend.installation.version.skill_id
    assert binding["version_id"] == backend.installation.version.version_id
    assert binding["managed"] is True
    assert _public(record, "mcp_runtime_unavailable")["readiness"]["ready"] is False
    assert _public(record.model_copy(update={"enabled": False}))["readiness"] == {
        "ready": False, "reason": "disabled",
    }
    assert "artifact_ref" not in str(public) and "plugin_origin" not in str(public)


def test_skill_enable_checks_current_publication_revision_and_package_manifest():
    from agent_core.application.plugin_installations import PluginInstallationService
    from agent_core.ports.extensions import ExtensionRevisionConflictError

    async def check():
        backend, record = skill_plugin()
        store, extensions = AsyncMock(), AsyncMock()
        store.get.return_value = record.model_copy(update={"enabled": False})
        extensions.get_skill.return_value = backend.installation
        extensions.get_skill_publication.return_value = backend.publication
        service = PluginInstallationService(store, extensions, AsyncMock(), AsyncMock(), "test")
        args = dict(scope=record.scope, operated_by="operator", installation_id="plugin-a",
                    expected_revision=1, payload={"enabled": True})
        assert await service.readiness(record) == "ready"
        off = PluginInstallationService(
            store, extensions, AsyncMock(), AsyncMock(), "test", skill_available=False,
        )
        assert await off.readiness(record) == "skill_runtime_unavailable"
        with pytest.raises(ExtensionRevisionConflictError, match="skill_runtime"):
            await off.update(**args)
        for changes in ({"state": "pending"}, {"manifest": ()}):
            extensions.get_skill_publication.return_value = backend.publication.model_copy(
                update=changes)
            with pytest.raises(ExtensionRevisionConflictError, match="component"):
                await service.update(**args)
        extensions.get_skill_publication.return_value = backend.publication
        extensions.get_skill.return_value = backend.installation.model_copy(update={"revision": 2})
        with pytest.raises(ExtensionRevisionConflictError, match="component"):
            await service.update(**args)
        store.save.assert_not_awaited()
    asyncio.run(check())


def test_direct_mcp_selectability_reuses_fresh_cached_catalog_without_discovery():
    from agent_core.ports.extensions import ExtensionNotFoundError
    from zebra_agent_api.extension_reads import _described_record

    from tests.agent_storage.test_postgres_plugin_installations import _catalog, _record

    async def check():
        connection = _record().bindings[0].connection
        catalogs = AsyncMock()
        catalogs.latest.return_value = _catalog(connection)
        ready = await _described_record(connection, None, catalogs)
        assert ready["selectable"] is True and ready["tool_count"] == 1
        disabled = await _described_record(connection.model_copy(update={"enabled": False}),
                                           None, catalogs)
        assert disabled["selectable"] is False
        catalogs.latest.side_effect = ExtensionNotFoundError
        absent = await _described_record(connection, None, catalogs)
        assert absent["selectable"] is False and absent["tool_count"] == 0
        off = await _described_record(connection, None)
        assert off["selectable"] is False
        assert not {"catalog_digest", "credential_ref", "tools", "session_id"} & ready.keys()
    asyncio.run(check())


@pytest.mark.parametrize("legacy", [False, True])
def test_skill_inventory_marks_rebound_legacy_and_orphan_package_origins_once_per_page(legacy):
    import json

    from agent_core.ports.extensions import SkillInstallationPage
    from agent_security.extension_authority import extension_scope_from_grant
    from fastapi import Request
    from zebra_agent_api.extension_reads import extension_read_response

    from tests.agent_security.test_extension_authority import _verified
    from tests.agent_storage.test_postgres_plugin_installations import _record

    async def check():
        verified = _verified(scopes=["extensions.read"])
        scope = extension_scope_from_grant(verified, permission="extensions.read")
        backend, original = skill_plugin(legacy=legacy, enabled=False)
        skill = backend.installation.model_copy(update={"scope": scope})
        original = original.model_copy(update={"scope": scope, "bindings": (
            original.bindings[0].model_copy(update={"installation": skill}),)})
        # Current bindings no longer include the old Skill; only immutable r1 does.
        values = _record().model_dump()
        values["scope"] = scope
        values["revision"] = 3
        values["bindings"][0]["connection"]["scope"] = scope
        rebound = type(original).model_validate(values)
        store, plugins = AsyncMock(), AsyncMock()
        store.list_skills.return_value = SkillInstallationPage(items=(skill,))
        plugins.list.return_value = PluginInstallationPage(items=(rebound,) if legacy else ())
        plugins.get_creation.return_value = original
        request = Request({"type": "http", "method": "GET",
                           "path": "/v1/extensions/skill-installations",
                           "headers": [], "query_string": b""})
        request.state.verified_host_grant = verified
        response = await extension_read_response(request, store=store, deployment="cloud",
                                                  plugin_installations=plugins)
        assert response.status_code == 200
        assert json.loads(response.body)["items"][0]["managed"] is True
        assert plugins.list.await_count == int(legacy)
        assert plugins.get_creation.await_count == int(legacy)
    asyncio.run(check())
