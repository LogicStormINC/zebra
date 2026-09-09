"""Native configuration tools preserve authority and reuse revision-guarded services."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.skill_publications import SkillPublication
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolIdempotency, ToolRisk
from agent_core.ports.extensions import (
    ExtensionStore,
    McpConnectionPage,
    SkillInstallationPage,
)
from agent_tools.extension_management import ExtensionManagementTools, management_contracts
from agent_tools.skill_publications import _candidate

from tests.agent_core.test_extensions import connection
from tests.agent_core.test_skill_installation_creation import installation_store, payload
from tests.agent_tools.test_skill_publications import archive
from tests.api.test_extension_reads import SCOPE, SKILL


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(tool_call_id=new_tool_call_id(), name="extensions." + name,
                    arguments=arguments, created_at=datetime(2026, 9, 9, tzinfo=UTC))


def test_contracts_separate_read_and_revision_guarded_writes() -> None:
    contracts = management_contracts()
    assert len(contracts) == 8
    for contract in contracts:
        reading = contract.name == "extensions.list"
        assert contract.risk == (ToolRisk.READ if reading else ToolRisk.WRITE)
        assert contract.scopes == ("extensions.read" if reading else "extensions.manage",)
        assert contract.idempotency == (
            ToolIdempotency.NONE if reading else ToolIdempotency.REQUIRED
        )


@pytest.mark.parametrize("kind", ["skill", "mcp"])
def test_list_scoped_public_records(kind: str) -> None:
    store = AsyncMock(spec=ExtensionStore)
    authorize = Mock(return_value=SCOPE)
    store.list_skills.return_value = SkillInstallationPage(items=(SKILL,), next_cursor="next")
    store.list_mcp.return_value = McpConnectionPage(items=(connection(
        scope=SCOPE, auth_mode="bearer", auth_state="ready", credential_ref="vault:secret",
    ),), next_cursor="next")
    result = ExtensionManagementTools(store, authorize).execute(call("list", kind=kind, limit=1))
    assert result.status == ToolCallStatus.EXECUTED
    output = json.loads(result.output)
    assert len(output["items"]) == 1 and output["next_cursor"] == "next"
    authorize.assert_called_once_with("extensions.read")
    getter = store.list_skills if kind == "skill" else store.list_mcp
    assert getter.await_args.kwargs["scope"] == SCOPE
    assert getter.await_args.kwargs["page"].limit == 1
    assert all(text not in result.output for text in ("vault:secret", "credential_ref", "scope"))


@pytest.mark.parametrize("auth_mode", ["none", "bearer"])
def test_add_mcp_starts_disabled_and_reports_pending_auth(auth_mode: str) -> None:
    store = AsyncMock(spec=ExtensionStore)
    authorize = Mock(return_value=SCOPE)
    result = ExtensionManagementTools(store, authorize).execute(call(
        "add_mcp", endpoint="https://mcp.example/api", transport="streamable_http",
        auth_mode=auth_mode,
    ))
    assert result.status == ToolCallStatus.EXECUTED
    output = json.loads(result.output)
    saved = store.save_mcp.await_args.kwargs["connection"]
    assert saved.scope == SCOPE and saved.revision == 1 and saved.enabled is False
    assert saved.credential_ref is None
    assert output["configuration"]["auth_state"] == (
        "pending" if auth_mode == "bearer" else "not_required"
    )
    assert output["current_turn_changed"] is False
    assert output["effective"] == "future_eligible_turn"
    assert authorize.call_count >= 2
    authorize.assert_called_with("extensions.manage")


def test_install_published_skill_then_enable_at_current_revision() -> None:
    store = installation_store()
    tools = ExtensionManagementTools(store, lambda permission: SCOPE)
    result = tools.execute(call("install_skill", **payload(store)))
    assert result.status == ToolCallStatus.EXECUTED
    saved = store.save_skill.await_args.kwargs["installation"]
    assert saved.scope == SCOPE and saved.enabled is False and saved.revision == 1
    assert saved.version == store.get_skill_publication.return_value.version
    assert all(text not in result.output for text in ("artifact_ref", "receipt", "scope"))
    store.get_skill.return_value = saved
    result = tools.execute(call("set_enabled", kind="skill", object_id=saved.installation_id,
                                expected_revision=1, enabled=True))
    assert result.status == ToolCallStatus.EXECUTED
    updated = store.save_skill.await_args.kwargs["installation"]
    assert updated.enabled is True and updated.revision == 2
    assert store.save_skill.await_args.kwargs["expected_revision"] == 1


@pytest.mark.parametrize("extra", ["scope", "headers", "token", "command", "enabled"])
def test_extra_arguments_rejected_before_authority_and_storage(extra: str) -> None:
    store = AsyncMock(spec=ExtensionStore)
    authorize = Mock(return_value=SCOPE)
    result = ExtensionManagementTools(store, authorize).execute(call(
        "add_mcp", endpoint="https://mcp.example", transport="sse", **{extra: "secret"},
    ))
    assert result.status == ToolCallStatus.FAILED and result.output == "invalid_arguments"
    authorize.assert_not_called()
    assert not store.mock_calls


@pytest.mark.parametrize("operation", ["list", "set_enabled"])
def test_permission_denial_is_redacted_before_storage(operation: str) -> None:
    store = AsyncMock(spec=ExtensionStore)
    authorize = Mock(side_effect=PermissionError("Bearer secret tenant-private"))
    args = {"kind": "mcp"}
    if operation == "set_enabled":
        args |= {"object_id": "mcp", "expected_revision": 1, "enabled": True}
    result = ExtensionManagementTools(store, authorize).execute(call(operation, **args))
    assert result.status == ToolCallStatus.FAILED
    assert result.output == "management_unavailable_or_not_authorized"
    assert not store.mock_calls


@pytest.mark.parametrize("operation", ["list", "set_enabled"])
def test_foreign_records_hidden_without_write(operation: str) -> None:
    store = AsyncMock(spec=ExtensionStore)
    foreign = connection(scope=SCOPE.model_copy(update={"principal_id": "foreign-secret"}))
    store.list_mcp.return_value = McpConnectionPage(items=(foreign,))
    store.get_mcp.return_value = foreign
    args = {"kind": "mcp"}
    if operation == "set_enabled":
        args |= {"object_id": "mcp", "expected_revision": 1, "enabled": True}
    result = ExtensionManagementTools(store, lambda permission: SCOPE).execute(
        call(operation, **args),
    )
    assert result.status == ToolCallStatus.FAILED and result.output == "not_found"
    store.save_mcp.assert_not_awaited()


def test_revision_conflict_requires_relisting_without_write() -> None:
    store = AsyncMock(spec=ExtensionStore)
    store.get_mcp.return_value = connection(scope=SCOPE, revision=2)
    result = ExtensionManagementTools(store, lambda permission: SCOPE).execute(call(
        "set_enabled", kind="mcp", object_id="mcp", expected_revision=1, enabled=True,
    ))
    assert result.status == ToolCallStatus.FAILED
    assert result.output == "revision_conflict_list_and_retry"
    store.save_mcp.assert_not_awaited()


def test_refresh_unavailable_and_success_do_not_claim_current_turn_activation() -> None:
    store = AsyncMock(spec=ExtensionStore)
    request = call("refresh_mcp", connection_id="mcp", expected_revision=2)
    result = ExtensionManagementTools(store, lambda permission: SCOPE).execute(request)
    assert result.status == ToolCallStatus.EXECUTED
    assert json.loads(result.output) == {"status": "refresh_not_available", "usable": False}
    refresh = AsyncMock(return_value=3)
    result = ExtensionManagementTools(store, lambda permission: SCOPE, refresh).execute(request)
    assert result.status == ToolCallStatus.EXECUTED
    assert json.loads(result.output) == {
        "status": "catalog_refreshed", "tool_count": 3,
        "effective": "future_eligible_turn", "current_turn_changed": False,
    }
    refresh.assert_awaited_once_with("mcp", 2)
    refresh.side_effect = RuntimeError("Authorization: Bearer private-secret")
    failed = ExtensionManagementTools(store, lambda permission: SCOPE, refresh).execute(request)
    assert failed.status == ToolCallStatus.FAILED
    assert "private-secret" not in failed.output


def test_update_mcp_endpoint_disables_and_clears_old_credentials() -> None:
    store = AsyncMock(spec=ExtensionStore)
    store.get_mcp.return_value = connection(
        scope=SCOPE, enabled=True, auth_mode="bearer", auth_state="ready",
        credential_ref="vault:old-secret",
    )
    result = ExtensionManagementTools(store, lambda permission: SCOPE).execute(call(
        "update_mcp", object_id="mcp", expected_revision=1,
        endpoint="https://new.example/mcp", transport="streamable_http", auth_mode="bearer",
    ))
    assert result.status == ToolCallStatus.EXECUTED
    saved = store.save_mcp.await_args.kwargs["connection"]
    assert saved.endpoint == "https://new.example/mcp" and saved.revision == 2
    assert saved.enabled is False and saved.credential_ref is None and saved.auth_state == "pending"
    assert "old-secret" not in result.output
    assert json.loads(result.output)["current_turn_changed"] is False


def test_authority_lost_during_read_prevents_save() -> None:
    store = AsyncMock(spec=ExtensionStore)
    authorize = Mock(return_value=SCOPE)

    async def lose_authority(**kwargs):
        authorize.side_effect = PermissionError("lease lost")
        return connection(scope=SCOPE, enabled=False)

    store.get_mcp.side_effect = lose_authority
    result = ExtensionManagementTools(store, authorize).execute(call(
        "set_enabled", kind="mcp", object_id="mcp", expected_revision=1, enabled=True,
    ))
    assert result.status == ToolCallStatus.FAILED
    store.save_mcp.assert_not_awaited()


@pytest.mark.parametrize("change", ["valid", "foreign", "unpublished", "different_skill",
                                   "revision"])
def test_skill_upgrade_requires_same_owned_published_skill(change: str) -> None:
    store = installation_store()
    tools = ExtensionManagementTools(store, lambda permission: SCOPE)
    assert tools.execute(call("install_skill", **payload(store))).status == ToolCallStatus.EXECUTED
    current = store.save_skill.await_args.kwargs["installation"].model_copy(
        update={"enabled": True},
    )
    store.save_skill.reset_mock()
    store.get_skill.return_value = current
    candidate = _candidate(archive("Updated body", version="v2"), SCOPE, "test")
    published = SkillPublication.model_validate(candidate.model_dump() | {
        "state": "ready", "receipt": ArtifactObjectReceipt(
            expectation=candidate.expectation, object_version="2", verified_at=datetime.now(UTC),
        ),
    })
    store.get_skill_publication.return_value = (
        published.model_copy(update={"scope": SCOPE.model_copy(update={"principal_id": "other"})})
        if change == "foreign" else candidate if change == "unpublished" else published
    )
    result = tools.execute(call(
        "update_skill", object_id=current.installation_id,
        expected_revision=2 if change == "revision" else 1,
        skill_id="another-skill" if change == "different_skill" else published.version.skill_id,
        version_id=published.version.version_id,
    ))
    if change == "valid":
        assert result.status == ToolCallStatus.EXECUTED
        saved = store.save_skill.await_args.kwargs["installation"]
        assert saved.version == published.version and saved.revision == 2 and saved.enabled
        assert saved.installation_id == current.installation_id
    else:
        assert result.status == ToolCallStatus.FAILED
        store.save_skill.assert_not_awaited()
        if change == "revision":
            assert result.output == "revision_conflict_list_and_retry"
