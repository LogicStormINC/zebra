from pathlib import Path

import pytest
from agent_core.domain.agent_definitions import AgentDefinition
from agent_storage import SQLiteSkillsStateStore
from agent_tools.agent_definitions import resolve_agent_definition_context
from agent_tools.skills_scope import SkillScope, build_scoped_skill_roots


def test_definition_refs_resolve_from_scoped_skill_catalog(tmp_path: Path) -> None:
    system_root = tmp_path / "system"
    admin_root = tmp_path / "admin"
    _write_skill(system_root, "system-prompt", "Follow the configured system policy.")
    _write_skill(admin_root, "evidence", "Use the evidence lookup capability.")

    context = resolve_agent_definition_context(
        AgentDefinition(
            agent_id="agent-neutral",
            version="1.0.0",
            system_prompt_ref="system://system-prompt",
            skill_refs=("skill://evidence",),
        ),
        build_scoped_skill_roots(system=[system_root], admin=[admin_root]),
    )

    assert context is not None
    assert "configured system policy" in context.render()
    assert "evidence lookup capability" in context.render()


@pytest.mark.parametrize(
    ("scope", "root_name"),
    ((SkillScope.USER, "user"), (SkillScope.REPO, "repo")),
)
def test_definition_skill_ref_rejects_untrusted_scope(
    tmp_path: Path,
    scope: SkillScope,
    root_name: str,
) -> None:
    root = tmp_path / root_name
    _write_skill(root, "evidence", "Untrusted guidance.")
    roots = (
        build_scoped_skill_roots(user=[root])
        if scope is SkillScope.USER
        else build_scoped_skill_roots(repo=[root])
    )

    with pytest.raises(ValueError, match="trusted scope"):
        resolve_agent_definition_context(
            AgentDefinition(
                agent_id="agent-neutral",
                version="1.0.0",
                skill_refs=("skill://evidence",),
            ),
            roots,
        )


def test_definition_skill_ref_rejects_disabled_source(tmp_path: Path) -> None:
    root = tmp_path / "admin"
    _write_skill(root, "evidence", "Disabled guidance.")
    state = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    state.set_enabled(name="evidence", scope="admin", enabled=False, operator="test")

    with pytest.raises(ValueError, match="cannot be resolved"):
        resolve_agent_definition_context(
            AgentDefinition(
                agent_id="agent-neutral",
                version="1.0.0",
                skill_refs=("skill://evidence",),
            ),
            build_scoped_skill_roots(admin=[root]),
            skills_state=state,
        )


def test_definition_context_digest_rejects_changed_skill_content(tmp_path: Path) -> None:
    root = tmp_path / "system"
    skill = root / "evidence"
    _write_skill(root, "evidence", "Original guidance.")
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        skill_refs=("skill://evidence",),
    )
    context = resolve_agent_definition_context(
        definition,
        build_scoped_skill_roots(system=[root]),
    )
    bound = definition.model_copy(
        update={"resolved_context_digest": context.resolved_context_digest}
    )
    (skill / "SKILL.md").write_text(
        "\n".join(
            (
                "---",
                "name: evidence",
                "description: evidence guidance",
                "---",
                "Changed guidance.",
                "",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="digest"):
        resolve_agent_definition_context(
            bound,
            build_scoped_skill_roots(system=[root]),
            require_digest=True,
        )


def test_system_ref_cannot_resolve_from_a_non_system_scope(tmp_path: Path) -> None:
    root = tmp_path / "user"
    _write_skill(root, "only-user", "User guidance.")

    with pytest.raises(ValueError, match="system skill"):
        resolve_agent_definition_context(
            AgentDefinition(
                agent_id="agent-neutral",
                version="1.0.0",
                system_prompt_ref="system://only-user",
            ),
            build_scoped_skill_roots(user=[root]),
        )


def _write_skill(root: Path, name: str, body: str) -> None:
    skill_root = root / name
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} guidance\n---\n{body}\n",
        encoding="utf-8",
    )
