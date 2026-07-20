from pathlib import Path

from agent_tools.skills_catalog import LocalSkillCatalog, SkillMetadata
from agent_tools.skills_scope import ScopedSkillRoot, SkillScope


def test_skill_scope_wire_values_are_stable() -> None:
    assert SkillScope.SYSTEM.value == "system"
    assert SkillScope.ADMIN.value == "admin"
    assert SkillScope.USER.value == "user"
    assert SkillScope.REPO.value == "repo"


def test_scoped_skill_root_is_frozen_and_carries_namespace_override() -> None:
    spec = ScopedSkillRoot(scope=SkillScope.ADMIN, root="/tmp/skills", namespace="ops")
    assert spec.scope is SkillScope.ADMIN
    assert spec.root == "/tmp/skills"
    assert spec.namespace == "ops"
    assert ScopedSkillRoot(scope=SkillScope.USER, root="/tmp/skills").namespace is None


def test_skill_metadata_defaults_scope_to_user_and_namespace_to_none() -> None:
    metadata = SkillMetadata("evidence", "Collect evidence.", ".")
    assert metadata.scope is SkillScope.USER
    assert metadata.namespace is None
    assert metadata.digest is None


def test_catalog_and_scope_layers_share_canonical_types(tmp_path: Path) -> None:
    root = tmp_path / "system"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: evidence\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    catalog = LocalSkillCatalog(
        (ScopedSkillRoot(scope=SkillScope.SYSTEM, root=str(root)),)
    )
    (items, ambiguous, _) = catalog.list()
    assert ambiguous == 0
    metadata = items[0]
    assert metadata.scope is SkillScope.SYSTEM
    assert metadata.namespace == "system"
    assert isinstance(metadata.digest, str)
