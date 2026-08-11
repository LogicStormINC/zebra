from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent_storage import SQLiteSkillsStateStore
from zebra_agent_api import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def _skill(root: Path, name: str, description: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nversion: 1.0.0\n---\n\n# {name}\nBODY\n",
        encoding="utf-8",
    )


def _settings(database: Path, skills_root: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        skill_roots=(str(skills_root),),
        skills_state_path=str(database.parent / "skills-state.sqlite"),
    )


def _app(tmp_path: Path, skills: Path):
    database = tmp_path / "sessions.sqlite"
    return create_app(database, settings=_settings(database, skills))


def test_admin_lists_skills_default_enabled(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    _skill(skills / "review", "review", "Review output")
    app = _app(tmp_path, skills)

    body = app.list_skills().body
    by_name = {skill["name"]: skill for skill in body["skills"]}
    assert set(by_name) == {"evidence", "review"}
    assert all(skill["enabled"] for skill in by_name.values())


def test_admin_disable_then_enable_round_trips(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    app = _app(tmp_path, skills)

    disabled = app.disable_skill("evidence", {"operator": "op-1"}).body
    assert disabled["enabled"] is False
    by_name = {skill["name"]: skill for skill in app.list_skills().body["skills"]}
    assert by_name["evidence"]["enabled"] is False

    enabled = app.enable_skill("evidence", {}).body
    assert enabled["enabled"] is True
    by_name = {skill["name"]: skill for skill in app.list_skills().body["skills"]}
    assert by_name["evidence"]["enabled"] is True


def test_admin_show_and_not_found(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    app = _app(tmp_path, skills)

    detail = app.show_skill("evidence")
    assert detail.status_code == 200
    assert detail.body["skills"][0]["name"] == "evidence"

    missing = app.show_skill("ghost")
    assert missing.status_code == 404


def test_admin_disable_unknown_skill_returns_not_found(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    app = _app(tmp_path, skills)

    response = app.disable_skill("ghost", {})
    assert response.status_code == 404


def test_admin_private_install_enable_and_owner_projection(tmp_path: Path) -> None:
    private_root = tmp_path / "skills"
    _skill(private_root / ".zebra-private" / "owner-a" / "review", "review", "Private review")
    app = _app(tmp_path, private_root)

    assert app.list_skills("owner-b").body["skills"] == []
    listed = app.list_skills("owner-a").body["skills"]
    assert listed[0]["owner"] == "owner-a"
    assert listed[0]["installed"] is False

    installed = app.install_skill("review", {"owner": "owner-a", "operator": "op"})
    assert installed.status_code == 200
    assert installed.body["installed"] is True
    assert installed.body["enabled"] is False
    assert app.enable_skill("review", {"owner": "owner-a", "version": "1.0.0"}).status_code == 400

    enabled = app.enable_skill("review", {"owner": "owner-a"})
    assert enabled.status_code == 200
    assert enabled.body["enabled"] is True
    assert app.list_skills("owner-b").body["skills"] == []


def test_private_owner_cannot_disable_a_system_skill(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    system = tmp_path / "system"
    _skill(system / "sys-review", "sys-review", "System review")
    settings = replace(_settings(database, tmp_path / "skills"), skill_roots_system=(str(system),))
    app = create_app(database, settings=settings)

    response = app.disable_skill("sys-review", {"owner": "owner-a", "operator": "test"})

    assert response.status_code == 404
    assert SQLiteSkillsStateStore(settings.skills_state_path).get_state(
        name="sys-review", scope="system"
    ) is None
