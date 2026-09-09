import asyncio

import pytest
from agent_core.domain.identifiers import SessionId
from agent_core.ports.extensions import ExtensionSkillAuthorizationError, SkillInstallationPage
from zebra_agent_api.app import create_app
from zebra_agent_api.extension_task_selection import validate_task_skill_selection
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.session_queue import create_queued_session

from tests.agent_security.test_extension_authority import _verified
from tests.api.test_extension_turn_admission import _admission
from tests.api.test_session_command_routes import _seed_ready_session


@pytest.mark.parametrize("skill_id", ["skill-01", "120349ee-8526-5f82-bb83-304d4b6ea421"])
def test_selected_skills_are_persisted_in_task_ceiling(tmp_path, skill_id):
    database_path, _, _ = _seed_ready_session(tmp_path)
    app = create_app(database_path=database_path)
    parsed = parse_create_session_payload({
        "prompt": "go", "workspace": str(tmp_path), "skill_components": [skill_id],
    })
    assert not isinstance(parsed, ApiResponse)
    response = create_queued_session(app.stores, parsed)
    from uuid import UUID

    workspace = app.stores.workspaces.get_workspace(SessionId(UUID(response.body["session_id"])))
    assert workspace.skill_components == (skill_id,)
    assert response.body["skill_components"] == [skill_id]


@pytest.mark.parametrize("raw", [None, "skill", [1], ["duplicate", "duplicate"], ["../x"]])
def test_invalid_skill_selection_is_rejected(raw):
    assert validate_task_skill_selection({"skill_components": raw}, None, None).status_code == 400


def test_empty_selection_requires_no_extension_runtime():
    assert validate_task_skill_selection({}, None, None) is None


def test_nonempty_selection_requires_runtime_and_verified_grant():
    payload = {"skill_components": ["skill-01"]}
    assert validate_task_skill_selection(payload, _verified(), None).status_code == 503
    admission, _, _ = _admission(2)
    assert validate_task_skill_selection(payload, None, admission).status_code == 403


def test_enabled_selection_requires_published_exact_scope_authorization():
    admission, store, _ = _admission(2)
    verified = _verified(scopes=["agent.run"])
    result = validate_task_skill_selection({"skill_components": ["skill-01"]}, verified, admission)
    assert result is None
    call = store.authorize_frozen_skills.await_args.kwargs
    assert call["scope"] == store.list_skills.await_args.kwargs["scope"]
    assert tuple(item.version.skill_id for item in call["installations"]) == ("skill-01",)


@pytest.mark.parametrize("skill", ["skill-00", "other-user-skill"])
def test_disabled_or_other_user_selection_is_rejected(skill):
    admission, store, _ = _admission(2)
    result = validate_task_skill_selection({"skill_components": [skill]}, _verified(), admission)
    assert result.status_code == 403
    store.authorize_frozen_skills.assert_not_awaited()


def test_revoked_publication_is_rejected():
    admission, store, _ = _admission(2)
    store.authorize_frozen_skills.side_effect = ExtensionSkillAuthorizationError("revoked")
    assert validate_task_skill_selection(
        {"skill_components": ["skill-01"]}, _verified(), admission,
    ).status_code == 403


def test_next_selection_uses_upgrade_without_changing_skill_ceiling():
    admission, store, _ = _admission(2)
    old = store.list_skills.return_value.items[1]
    upgraded = old.model_copy(update={
        "revision": 2, "version": old.version.model_copy(update={"version_id": "v2"}),
    })
    store.list_skills.return_value = SkillInstallationPage(items=(upgraded,))
    selected = asyncio.run(admission._list_enabled_skills(old.scope, frozenset({"skill-01"})))
    assert selected == [upgraded]
