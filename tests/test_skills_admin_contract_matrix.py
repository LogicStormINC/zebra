from __future__ import annotations

from pathlib import Path

from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_catalog import LocalSkillCatalog


def _skill(root: Path, name: str, description: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nBODY\n",
        encoding="utf-8",
    )


def test_state_none_means_all_skills_visible(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    _skill(skills / "review", "review", "Review output")
    catalog = LocalSkillCatalog((str(skills),))
    names = {metadata.name for metadata in catalog.list()[0]}
    assert names == {"evidence", "review"}


def test_catalog_filters_disabled_components(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    _skill(skills / "review", "review", "Review output")

    store = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    store.set_enabled(name="evidence", scope="user", enabled=False, operator="op")

    filtered = LocalSkillCatalog((str(skills),), skills_state=store)
    names = {metadata.name for metadata in filtered.list()[0]}
    assert names == {"review"}


def test_re_enabling_restores_visibility(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")

    store = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    store.set_enabled(name="evidence", scope="user", enabled=False, operator="op")
    disabled_catalog = LocalSkillCatalog((str(skills),), skills_state=store)
    assert {m.name for m in disabled_catalog.list()[0]} == set()

    store.set_enabled(name="evidence", scope="user", enabled=True, operator="op")
    enabled_catalog = LocalSkillCatalog((str(skills),), skills_state=store)
    assert {m.name for m in enabled_catalog.list()[0]} == {"evidence"}


def test_disabled_filter_is_per_name_scope(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills / "evidence", "evidence", "Gather evidence")
    # disabling a (name, scope) pair that is not the component's own scope leaves it visible
    store = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    store.set_enabled(name="evidence", scope="system", enabled=False, operator="op")
    catalog = LocalSkillCatalog((str(skills),), skills_state=store)
    names = {metadata.name for metadata in catalog.list()[0]}
    assert names == {"evidence"}
