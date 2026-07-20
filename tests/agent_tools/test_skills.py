from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_tools import SkillsListTool, SkillsReadTool
from agent_tools.skills_catalog import LocalSkillCatalog, SkillCatalogError


def test_skill_tools_progressively_disclose_metadata_then_content(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "research/evidence", "evidence", "Collect bounded evidence.")
    (skill / "references").mkdir()
    (skill / "references" / "method.md").write_text("METHOD-127\n", encoding="utf-8")
    catalog = LocalSkillCatalog((tmp_path,))

    listed = SkillsListTool(catalog).handle(_call("skills.list", {}))
    read = SkillsReadTool(catalog).handle(
        _call("skills.read", {"name": "evidence", "file_path": "references/method.md"})
    )

    assert listed.status is ToolCallStatus.EXECUTED
    assert listed.output == (
        "[UNTRUSTED LOCAL SKILL METADATA]\nevidence: Collect bounded evidence."
    )
    assert "METHOD-127" not in listed.output
    assert read.status is ToolCallStatus.EXECUTED
    assert read.output == "[UNTRUSTED LOCAL SKILL GUIDANCE]\nMETHOD-127\n"
    assert read.metadata["untrusted_procedural_guidance"] is True
    assert read.metadata["skill_digest"] is not None
    assert read.metadata["skill_scope"] == "user"
    assert read.metadata["skill_version"] is None
    assert read.metadata["provenance_source"] == read.metadata["source"]


def test_catalog_skips_dependencies_hidden_dirs_and_nested_support_skills(
    tmp_path: Path,
) -> None:
    _skill(tmp_path, "valid", "valid", "Visible.")
    _skill(tmp_path, "node_modules/blocked", "dependency", "Blocked.")
    parent = _skill(tmp_path, "parent", "parent", "Parent.")
    _skill(parent, "references/archived", "archived", "Blocked support package.")

    skills, _, _ = LocalSkillCatalog((tmp_path,)).list()

    assert [skill.name for skill in skills] == ["parent", "valid"]


def test_catalog_omits_ambiguous_names_across_roots(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _skill(first, "one", "duplicate", "First.")
    _skill(second, "two", "duplicate", "Second.")
    catalog = LocalSkillCatalog((first, second))

    skills, ambiguous_count, _ = catalog.list()

    assert skills == ()
    assert ambiguous_count == 1
    with pytest.raises(SkillCatalogError, match="ambiguous"):
        catalog.read("duplicate")


def test_oversized_skill_is_listed_but_full_body_remains_bounded(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "large", "large", "Large but discoverable.")
    with (skill / "SKILL.md").open("a", encoding="utf-8") as stream:
        stream.write("x" * 40_000)
    catalog = LocalSkillCatalog((tmp_path,))

    skills, _, _ = catalog.list()

    assert [item.name for item in skills] == ["large"]
    with pytest.raises(SkillCatalogError) as raised:
        catalog.read("large")
    assert raised.value.reason == "file_too_large"


def test_skill_list_bounds_aggregate_metadata_output(tmp_path: Path) -> None:
    for index in range(100):
        _skill(tmp_path, str(index), f"skill-{index:03d}", "x" * 1_000)

    result = SkillsListTool(LocalSkillCatalog((tmp_path,))).handle(
        _call("skills.list", {"limit": 100})
    )

    assert len(result.output.encode("utf-8")) <= 32_768
    assert result.metadata["skill_count"] < 100
    assert result.metadata["truncated"] is True


@pytest.mark.parametrize(
    ("file_path", "reason"),
    (
        ("../outside.md", "invalid_file_path"),
        ("/tmp/outside.md", "invalid_file_path"),
        ("notes.md", "unsupported_file"),
        ("references/.env", "sensitive_file"),
        ("references/api-token.md", "sensitive_file"),
    ),
)
def test_skill_read_rejects_unsafe_support_paths(
    tmp_path: Path, file_path: str, reason: str
) -> None:
    _skill(tmp_path, "safe", "safe", "Safe.")

    with pytest.raises(SkillCatalogError) as raised:
        LocalSkillCatalog((tmp_path,)).read("safe", file_path=file_path)

    assert raised.value.reason == reason


def test_skill_read_rejects_symlink_escape(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "safe", "safe", "Safe.")
    outside = tmp_path.parent / "outside-skill.md"
    outside.write_text("OUTSIDE\n", encoding="utf-8")
    (skill / "references").mkdir()
    (skill / "references" / "outside.md").symlink_to(outside)

    with pytest.raises(SkillCatalogError) as raised:
        LocalSkillCatalog((tmp_path,)).read("safe", file_path="references/outside.md")

    assert raised.value.reason == "path_outside_skill"


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    (
        ("skills.list", {"limit": True}),
        ("skills.list", {"extra": "no"}),
        ("skills.read", {"name": 1}),
        ("skills.read", {"name": "safe", "extra": "no"}),
    ),
)
def test_skill_tools_reject_malformed_arguments(
    tmp_path: Path, tool_name: str, arguments: dict[str, object]
) -> None:
    _skill(tmp_path, "safe", "safe", "Safe.")
    catalog = LocalSkillCatalog((tmp_path,))
    tool = SkillsListTool(catalog) if tool_name == "skills.list" else SkillsReadTool(catalog)

    result = tool.handle(_call(tool_name, arguments))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "invalid_arguments"


def _skill(root: Path, relative: str, name: str, description: str) -> Path:
    directory = root / relative
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nBODY-127\n",
        encoding="utf-8",
    )
    return directory


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
