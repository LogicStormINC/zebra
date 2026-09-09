import json
from unittest.mock import AsyncMock, Mock

from agent_core.domain.tools import ToolCallStatus
from agent_core.ports.extensions import SkillInstallationPage
from agent_tools.extension_management import ExtensionManagementTools

from tests.agent_core.test_skill_installation_creation import installation_store, payload
from tests.agent_tools.test_extension_management import call
from tests.api.test_extension_reads import SCOPE, SKILL


def test_import_enables_owned_publication_and_reimport_is_noop():
    store = installation_store()
    store.list_skills.return_value = SkillInstallationPage(items=(), next_cursor=None)

    async def save(**kwargs):
        value = kwargs["installation"]
        store.get_skill.return_value = value
        store.list_skills.return_value = SkillInstallationPage(items=(value,), next_cursor=None)
    store.save_skill.side_effect = save
    importer = AsyncMock(return_value=payload(store) | {"commit_sha": "a" * 40})
    authority = Mock(return_value=SCOPE)
    tools = ExtensionManagementTools(store, authority, import_skill=importer)
    result = tools.execute(call("import_skill", url="https://github.com/forjd/better-writing"))
    assert result.status is ToolCallStatus.EXECUTED
    output = json.loads(result.output)
    assert output["status"] == "installed_and_enabled"
    assert output["configuration"]["enabled"] is True
    assert output["effective"] == "next_user_turn"
    assert store.save_skill.await_count == 2
    repeated = tools.execute(call("import_skill", url="https://github.com/forjd/better-writing"))
    assert json.loads(repeated.output)["configuration"] == output["configuration"]
    assert store.save_skill.await_count == 2
    assert authority.call_count >= 4


def test_ambiguous_import_never_installs():
    store = installation_store()
    importer = AsyncMock(return_value={
        "status": "skill_selection_required", "candidates": ["a", "b"],
    })
    tools = ExtensionManagementTools(store, Mock(return_value=SCOPE), import_skill=importer)
    result = tools.execute(
        call("import_skill", url="https://github.com/example/skills"),
    )
    assert json.loads(result.output)["status"] == "skill_selection_required"
    assert not store.mock_calls


def test_import_requires_authority_before_downloading():
    importer = AsyncMock()
    result = ExtensionManagementTools(installation_store(), Mock(side_effect=ValueError()),
                                      import_skill=importer).execute(
        call("import_skill", url="https://github.com/example/skills"),
    )
    assert result.status is ToolCallStatus.FAILED
    importer.assert_not_called()


def test_import_replay_cannot_claim_a_concurrent_different_version(monkeypatch):
    store = installation_store()
    store.list_skills.return_value = SkillInstallationPage(items=(), next_cursor=None)
    monkeypatch.setattr(
        "agent_tools.skill_import_installation.create_skill_installation",
        AsyncMock(return_value=(SKILL, False)),
    )
    importer = AsyncMock(return_value=payload(store))
    tools = ExtensionManagementTools(store, Mock(return_value=SCOPE), import_skill=importer)
    result = tools.execute(call("import_skill", url="https://github.com/example/skills"))
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "revision_conflict_list_and_retry"
    store.save_skill.assert_not_called()
