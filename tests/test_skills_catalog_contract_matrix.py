from pathlib import Path

from agent_tools.skills_catalog import (
    MAX_COMPATIBILITY_ENTRIES,
    MAX_METADATA_ENTRIES,
    LocalSkillCatalog,
    SkillCatalogError,
    SkillCatalogReason,
    SkillMetadata,
)


def test_skill_catalog_reason_wire_values_are_stable() -> None:
    expected = {
        SkillCatalogReason.INVALID_LIMIT: "invalid_limit",
        SkillCatalogReason.INVALID_ROOT: "invalid_root",
        SkillCatalogReason.DUPLICATE_ROOT: "duplicate_root",
        SkillCatalogReason.INVALID_SKILL: "invalid_skill",
        SkillCatalogReason.SKILL_NOT_FOUND: "skill_not_found",
        SkillCatalogReason.AMBIGUOUS_SKILL: "ambiguous_skill",
        SkillCatalogReason.FILE_NOT_FOUND: "file_not_found",
        SkillCatalogReason.PATH_OUTSIDE_SKILL: "path_outside_skill",
        SkillCatalogReason.FILE_TOO_LARGE: "file_too_large",
        SkillCatalogReason.BINARY_FILE: "binary_file",
        SkillCatalogReason.INVALID_ENCODING: "invalid_encoding",
        SkillCatalogReason.INVALID_FILE_PATH: "invalid_file_path",
        SkillCatalogReason.SENSITIVE_FILE: "sensitive_file",
        SkillCatalogReason.UNSUPPORTED_FILE: "unsupported_file",
        SkillCatalogReason.FILE_READ_FAILED: "file_read_failed",
        SkillCatalogReason.INVALID_ARGUMENTS: "invalid_arguments",
    }
    for member, value in expected.items():
        assert member.value == value
        assert member == value


def test_skill_metadata_optional_fields_default_backwards_compatible() -> None:
    metadata = SkillMetadata("evidence", "Collect bounded evidence.", ".")
    assert metadata.name == "evidence"
    assert metadata.description == "Collect bounded evidence."
    assert metadata.source == "."
    assert metadata.version is None
    assert metadata.license is None
    assert metadata.compatibility == ()
    assert dict(metadata.metadata) == {}
    assert metadata.digest is None


def test_skill_catalog_error_normalizes_reason_to_plain_str() -> None:
    via_enum = SkillCatalogError(SkillCatalogReason.INVALID_LIMIT, "detail")
    via_literal = SkillCatalogError("invalid_limit", "detail")
    assert via_enum.reason == "invalid_limit"
    assert isinstance(via_enum.reason, str)
    assert not isinstance(via_enum.reason, SkillCatalogReason)
    assert via_enum.reason == via_literal.reason


def test_frontmatter_parses_agent_skills_optional_fields(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "skill",
        "---\n"
        "name: skill\n"
        "description: A skill.\n"
        "version: 1.2.3\n"
        "license: MIT\n"
        "compatibility: >=0.1.0 <0.2.0\n"
        "author: team\n"
        "---\n",
    )
    (items, _, _) = LocalSkillCatalog((tmp_path,)).list()
    metadata = items[0]
    assert metadata.version == "1.2.3"
    assert metadata.license == "MIT"
    assert metadata.compatibility == (">=0.1.0", "<0.2.0")
    assert metadata.metadata["author"] == "team"


def test_frontmatter_remains_backward_compatible_with_name_description_only(
    tmp_path: Path,
) -> None:
    _write_skill(tmp_path, "skill", "---\nname: skill\ndescription: Minimal.\n---\n")
    (items, ambiguous, _) = LocalSkillCatalog((tmp_path,)).list()
    assert ambiguous == 0
    metadata = items[0]
    assert metadata.version is None
    assert metadata.license is None
    assert metadata.compatibility == ()
    assert dict(metadata.metadata) == {}


def test_frontmatter_unknown_fields_collect_into_metadata(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "skill",
        "---\nname: skill\ndescription: d\nowner: ops\ntags: experimental\n---\n",
    )
    (items, _, _) = LocalSkillCatalog((tmp_path,)).list()
    metadata = items[0]
    assert metadata.metadata["owner"] == "ops"
    assert metadata.metadata["tags"] == "experimental"


def test_frontmatter_rejects_too_many_compatibility_entries(tmp_path: Path) -> None:
    entries = " ".join(f"v{i}" for i in range(MAX_COMPATIBILITY_ENTRIES + 1))
    _write_skill(
        tmp_path,
        "skill",
        f"---\nname: skill\ndescription: d\ncompatibility: {entries}\n---\n",
    )
    (items, _, _) = LocalSkillCatalog((tmp_path,)).list()
    assert items == ()


def test_frontmatter_rejects_too_many_metadata_entries(tmp_path: Path) -> None:
    lines = "\n".join(f"extra{i}: value{i}" for i in range(MAX_METADATA_ENTRIES + 1))
    _write_skill(
        tmp_path,
        "skill",
        f"---\nname: skill\ndescription: d\n{lines}\n---\n",
    )
    (items, _, _) = LocalSkillCatalog((tmp_path,)).list()
    assert items == ()


def _write_skill(root: Path, name: str, frontmatter_body: str) -> None:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(frontmatter_body + "\n# body\n", encoding="utf-8")
