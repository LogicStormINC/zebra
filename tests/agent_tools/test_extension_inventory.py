"""Management inventory must not confuse installation with this Turn's tools."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    McpSnapshotEntry,
)
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionStore,
    McpConnectionPage,
    SkillInstallationPage,
)
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError, McpCatalogStore
from agent_tools.extension_management import ExtensionManagementTools
from agent_tools.skills_catalog import SkillCatalog, SkillMetadata

from tests.agent_core.test_extensions import connection
from tests.agent_tools.test_extension_management import call
from tests.api.test_extension_reads import SCOPE, SKILL


def inventory(**changes):
    selected = SKILL.model_copy(update={"enabled": True})
    other = selected.model_copy(
        update={
            "installation_id": "other",
            "version": selected.version.model_copy(update={"skill_id": "other-skill"}),
        }
    )
    mcp = connection(scope=SCOPE, enabled=True)
    catalog = McpToolCatalog(
        connection=mcp,
        protocol_version="2025-11-25",
        tools=(McpCatalogTool(name="fetch", input_schema_json='{"type":"object"}'),),
    )
    snapshot = ExtensionSnapshot(
        scope=SCOPE,
        session_id="session",
        turn_id="turn",
        skills=(selected,),
        mcp=(
            McpSnapshotEntry(
                connection=mcp,
                catalog_digest=catalog.digest,
                permissions=ExtensionPermissions(tools=("fetch",)),
            ),
        ),
    )
    store = AsyncMock(spec=ExtensionStore)
    store.list_skills.return_value = SkillInstallationPage(
        items=(selected, other), next_cursor="next"
    )
    store.list_mcp.return_value = McpConnectionPage(items=(mcp,))
    catalogs = AsyncMock(spec=McpCatalogStore)
    catalogs.get.return_value = catalogs.latest.return_value = catalog
    skills = Mock(spec=SkillCatalog)
    skills.list.return_value = (
        (
            SkillMetadata(
                name="readable",
                description="test",
                source="cloud",
                skill_id=selected.version.skill_id,
            ),
        ),
        0,
        False,
    )
    authorize = Mock(return_value=SCOPE)
    tools = ExtensionManagementTools(
        store, authorize, mcp_catalogs=catalogs, snapshot=snapshot, skill_catalog=skills, **changes
    )
    return tools, store, catalogs, skills, selected, other, mcp, snapshot


def records(tools, kind):
    result = tools.execute(call("list", kind=kind))
    assert result.metadata["route"] == "cloud_extension_management"
    return result, json.loads(result.output)


def test_installed_skill_is_readable_only_if_mounted_and_in_actual_live_catalog():
    tools, _, _, skills, _, _, _, _ = inventory()
    _, result = records(tools, "skill")
    mounted, unmounted = result["items"]
    assert mounted["installed"] and mounted["available_this_turn"]
    assert mounted["read_name"] == "readable"
    assert unmounted["installed"] and not unmounted["available_this_turn"]
    assert unmounted["unavailable_reason"] == "not_selected_for_turn"
    assert unmounted["read_name"] is None
    assert result["next_cursor"] == "next"
    skills.list.assert_called_once_with(limit=200)


@pytest.mark.parametrize(
    "change", ["disabled", "revision", "version", "not_in_live_catalog", "catalog_unavailable"]
)
def test_skill_installation_alone_cannot_claim_current_availability(change):
    tools, store, _, skills, selected, _, _, _ = inventory()
    if change == "disabled":
        selected = selected.model_copy(update={"enabled": False})
    if change == "revision":
        selected = selected.model_copy(update={"revision": 2})
    if change == "version":
        selected = selected.model_copy(
            update={"version": selected.version.model_copy(update={"version_id": "new"})}
        )
    if change == "not_in_live_catalog":
        skills.list.return_value = ((), 0, False)
    if change == "catalog_unavailable":
        skills.list.side_effect = RuntimeError("Authorization: Bearer private")
    store.list_skills.return_value = SkillInstallationPage(items=(selected,))
    result = tools.execute(call("list", kind="skill"))
    assert '"available_this_turn": true' not in result.output
    assert "private" not in result.output


def test_mcp_reuses_pinned_catalog_verification_and_does_not_suggest_refresh():
    tools, _, catalogs, _, _, _, mcp, snapshot = inventory()
    _, result = records(tools, "mcp")
    item = result["items"][0]
    assert item["catalog_verified"] and item["tool_count"] == 1
    assert item["available_this_turn"] and item["next_step"] is None
    catalogs.get.assert_awaited_once_with(
        scope=SCOPE,
        connection_id=mcp.connection_id,
        config_revision=mcp.revision,
        expected_digest=snapshot.mcp[0].catalog_digest,
    )
    catalogs.latest.assert_not_awaited()
    assert "endpoint" not in item and "credential_ref" not in item


@pytest.mark.parametrize(
    "failure",
    [ExtensionNotFoundError(), McpCatalogIntegrityError("private"), RuntimeError("secret")],
)
def test_missing_or_unverifiable_catalog_never_claims_verified(failure):
    tools, _, catalogs, _, _, _, _, _ = inventory()
    catalogs.get.side_effect = failure
    result = tools.execute(call("list", kind="mcp"))
    assert '"catalog_verified": true' not in result.output
    assert '"available_this_turn": true' not in result.output
    assert "private" not in result.output and "secret" not in result.output


def test_authority_denial_precedes_catalog_and_current_skill_checks():
    tools, store, catalogs, skills, *_ = inventory()
    tools.authorize.side_effect = PermissionError("private")
    for kind in ("skill", "mcp"):
        result = tools.execute(call("list", kind=kind))
        assert result.output == "management_unavailable_or_not_authorized"
    assert not store.mock_calls and not catalogs.mock_calls and not skills.mock_calls


def test_catalog_from_wrong_digest_is_not_a_verified_pinned_catalog():
    tools, _, catalogs, *_ = inventory()
    catalogs.get.return_value = catalogs.get.return_value.model_copy(
        update={"protocol_version": "2024-11-05"}
    )
    result = tools.execute(call("list", kind="mcp"))
    assert '"catalog_verified": true' not in result.output
    assert '"available_this_turn": true' not in result.output


def test_installed_mcp_with_valid_catalog_can_be_unselected_for_this_turn():
    from dataclasses import replace

    tools, _, catalogs, _, _, _, _, snapshot = inventory()
    tools = replace(tools, snapshot=snapshot.model_copy(update={"mcp": ()}))
    _, result = records(tools, "mcp")
    item = result["items"][0]
    assert item["catalog_verified"] and not item["available_this_turn"]
    assert item["next_step"] is None
    catalogs.latest.assert_awaited_once()
    catalogs.get.assert_not_awaited()


def test_unconfigured_mcp_catalog_is_unknown_without_refresh_advice():
    from dataclasses import replace

    tools, *_ = inventory()
    tools = replace(tools, mcp_catalogs=None)
    _, result = records(tools, "mcp")
    item = result["items"][0]
    assert item["catalog_verified"] is None
    assert item["tool_count"] is None and not item["available_this_turn"]
    assert "refresh" not in item["next_step"].lower()


@pytest.mark.parametrize("state", ["disabled", "authentication"])
def test_ineligible_mcp_does_not_read_catalogs(state):
    tools, store, catalogs, _, _, _, mcp, _ = inventory()
    update = (
        {"enabled": False}
        if state == "disabled"
        else {"auth_mode": "bearer", "auth_state": "pending"}
    )
    # Validate the changed record exactly as a configuration store would.
    from agent_core.domain.extensions import McpConnection

    store.list_mcp.return_value = McpConnectionPage(
        items=(McpConnection.model_validate(mcp.model_dump() | update),)
    )
    _, result = records(tools, "mcp")
    assert not result["items"][0]["catalog_verified"]
    assert not result["items"][0]["available_this_turn"]
    catalogs.get.assert_not_awaited()
    catalogs.latest.assert_not_awaited()
