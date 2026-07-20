from __future__ import annotations

from pathlib import Path

from zebra_agent_cli.cli import execute
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


def test_cli_skill_list(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    _skill(skills / "review", "review", "Review output")
    settings = _settings(tmp_path / "sessions.sqlite", skills)

    result = execute(["skill", "list"], settings=settings)
    assert result.command == "skill"
    names = {skill["name"]: skill for skill in result.payload["skills"]}
    assert set(names) == {"evidence", "review"}
    assert all(skill["enabled"] for skill in names.values())


def test_cli_skill_show_enable_disable(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    settings = _settings(tmp_path / "sessions.sqlite", skills)

    detail = execute(["skill", "show", "evidence"], settings=settings)
    assert detail.payload["skills"][0]["name"] == "evidence"

    disabled = execute(
        ["skill", "disable", "evidence", "--operator", "op"], settings=settings
    )
    assert disabled.payload["enabled"] is False

    listing = execute(["skill", "list"], settings=settings)
    evidence = next(
        skill for skill in listing.payload["skills"] if skill["name"] == "evidence"
    )
    assert evidence["enabled"] is False

    enabled = execute(["skill", "enable", "evidence"], settings=settings)
    assert enabled.payload["enabled"] is True
