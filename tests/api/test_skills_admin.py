from __future__ import annotations

from pathlib import Path

from zebra_agent_api import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def _skill(root: Path, name: str, description: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nBODY\n",
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
