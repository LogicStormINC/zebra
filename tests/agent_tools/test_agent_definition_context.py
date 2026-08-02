from pathlib import Path

import pytest
from agent_core.domain.agent_definitions import AgentDefinition
from agent_tools.agent_definitions import resolve_agent_definition_context
from agent_tools.skills_scope import build_scoped_skill_roots


def test_definition_refs_resolve_from_scoped_skill_catalog(tmp_path: Path) -> None:
    system_root = tmp_path / "system"
    user_root = tmp_path / "user"
    _write_skill(system_root, "system-prompt", "Follow the configured system policy.")
    _write_skill(user_root, "evidence", "Use the evidence lookup capability.")

    context = resolve_agent_definition_context(
        AgentDefinition(
            agent_id="agent-neutral",
            version="1.0.0",
            system_prompt_ref="system://system-prompt",
            skill_refs=("skill://evidence",),
        ),
        build_scoped_skill_roots(system=[system_root], user=[user_root]),
    )

    assert context is not None
    assert "configured system policy" in context.render()
    assert "evidence lookup capability" in context.render()


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
