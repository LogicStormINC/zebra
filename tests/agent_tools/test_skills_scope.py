from pathlib import Path

import pytest
from agent_tools.skills_catalog import LocalSkillCatalog
from agent_tools.skills_scope import (
    ScopedSkillRoot,
    SkillCatalogError,
    SkillScope,
    compute_skill_digest,
    default_namespace,
    normalize_scoped_roots,
    scope_priority,
)
from zebra_agent_config.settings import load_settings


def test_scope_priority_orders_higher_trust_first() -> None:
    assert scope_priority(SkillScope.SYSTEM) < scope_priority(SkillScope.ADMIN)
    assert scope_priority(SkillScope.ADMIN) < scope_priority(SkillScope.USER)
    assert scope_priority(SkillScope.USER) < scope_priority(SkillScope.REPO)


def test_default_namespace_matches_scope_value() -> None:
    for scope in SkillScope:
        assert default_namespace(scope) == scope.value


def test_compute_skill_digest_is_stable_and_distinct() -> None:
    first = compute_skill_digest(b"manifest", b"body")
    second = compute_skill_digest(b"manifest", b"body")
    assert first == second
    assert len(first) == 64
    assert first != compute_skill_digest(b"manifest-2", b"body")
    assert first != compute_skill_digest(b"manifest", b"body-2")


def test_normalize_scoped_roots_treats_bare_paths_as_user(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    normalized = normalize_scoped_roots((str(root),))
    assert len(normalized) == 1
    assert normalized[0].scope is SkillScope.USER
    assert normalized[0].root == str(root.resolve())


def test_normalize_scoped_roots_orders_by_scope_priority(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    system_root = tmp_path / "system"
    user_root.mkdir()
    system_root.mkdir()
    normalized = normalize_scoped_roots(
        (
            ScopedSkillRoot(scope=SkillScope.USER, root=str(user_root)),
            ScopedSkillRoot(scope=SkillScope.SYSTEM, root=str(system_root)),
        )
    )
    assert [item.scope for item in normalized] == [SkillScope.SYSTEM, SkillScope.USER]


def test_normalize_scoped_roots_rejects_missing_and_duplicate(tmp_path: Path) -> None:
    with pytest.raises(SkillCatalogError):
        normalize_scoped_roots((str(tmp_path / "missing"),))
    existing = tmp_path / "dup"
    existing.mkdir()
    with pytest.raises(SkillCatalogError):
        normalize_scoped_roots((str(existing), str(existing)))


def test_catalog_higher_scope_wins_on_cross_scope_collision(tmp_path: Path) -> None:
    system_root = tmp_path / "system"
    user_root = tmp_path / "user"
    _skill(system_root, "shared", "Shared system guidance.")
    _skill(user_root, "shared", "Shared user guidance.")
    catalog = LocalSkillCatalog(
        (
            ScopedSkillRoot(scope=SkillScope.USER, root=str(user_root)),
            ScopedSkillRoot(scope=SkillScope.SYSTEM, root=str(system_root)),
        )
    )
    items, ambiguous, _ = catalog.list()
    assert [item.name for item in items] == ["shared"]
    assert ambiguous == 0
    assert items[0].scope is SkillScope.SYSTEM
    assert items[0].namespace == "system"


def test_catalog_same_scope_collision_remains_ambiguous(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _skill(first, "shared", "First user guidance.")
    _skill(second, "shared", "Second user guidance.")
    catalog = LocalSkillCatalog((str(first), str(second)))
    items, ambiguous, _ = catalog.list()
    assert items == ()
    assert ambiguous == 1
    with pytest.raises(SkillCatalogError, match="ambiguous"):
        catalog.read("shared")


def test_catalog_assigns_scope_namespace_and_digest(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _skill(repo_root, "evidence", "Collect bounded evidence.")
    catalog = LocalSkillCatalog(
        (ScopedSkillRoot(scope=SkillScope.REPO, root=str(repo_root), namespace="team"),)
    )
    (items, _, _) = catalog.list()
    metadata = items[0]
    assert metadata.scope is SkillScope.REPO
    assert metadata.namespace == "team"
    assert metadata.digest is not None
    assert len(metadata.digest) == 64


def test_catalog_digest_is_stable_across_catalogs(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _skill(root, "evidence", "Collect bounded evidence.")
    first = LocalSkillCatalog((str(root),)).list()[0][0]
    second = LocalSkillCatalog((str(root),)).list()[0][0]
    assert first.digest is not None
    assert first.digest == second.digest


def test_settings_exposes_four_scope_root_fields(tmp_path: Path) -> None:
    system_dir = tmp_path / "system"
    admin_dir = tmp_path / "admin"
    repo_dir = tmp_path / "repo"
    user_dir = tmp_path / "user"
    for directory in (system_dir, admin_dir, repo_dir, user_dir):
        directory.mkdir()
    settings = load_settings(
        env={
            "ZEBRA_SKILL_ROOTS": str(user_dir),
            "ZEBRA_SKILL_ROOTS_SYSTEM": str(system_dir),
            "ZEBRA_SKILL_ROOTS_ADMIN": str(admin_dir),
            "ZEBRA_SKILL_ROOTS_REPO": str(repo_dir),
        }
    )
    assert settings.skill_roots == (str(user_dir.resolve()),)
    assert settings.skill_roots_system == (str(system_dir.resolve()),)
    assert settings.skill_roots_admin == (str(admin_dir.resolve()),)
    assert settings.skill_roots_repo == (str(repo_dir.resolve()),)


def _skill(root: Path, name: str, description: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nBODY-127\n",
        encoding="utf-8",
    )
