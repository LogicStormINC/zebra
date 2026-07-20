from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_tools import SkillsReadTool
from agent_tools.skills_catalog import LocalSkillCatalog

_FIXTURES = Path("evals/fixtures/skills")
_CASES = Path("evals/cases")

# case_id -> fixture skill name (the `name` frontmatter field the catalog exposes)
_CASE_SKILLS = {
    "skill-guided-refactor": "guided-refactor",
    "skill-guided-bugfix": "guided-bugfix",
}


def test_skill_eval_cases_force_replay_through_skills_read_with_digest() -> None:
    catalog = LocalSkillCatalog((_FIXTURES,))
    tool = SkillsReadTool(catalog)

    for case_id, skill_name in _CASE_SKILLS.items():
        case = json.loads((_CASES / f"{case_id.replace('-', '_')}.json").read_text())
        assert case["min_tool_results"] >= 2, f"{case_id} must force skills.read replay"

        # Replay the skills.read path at least twice (min_tool_results >= 2).
        for _ in range(case["min_tool_results"]):
            result = tool.handle(_read_call(skill_name))
            assert result.status is ToolCallStatus.EXECUTED
            metadata = result.metadata
            assert metadata["skill_digest"] == case["expected_skill_digest"]
            assert metadata["skill_digest"]
            assert metadata["skill_scope"] == "user"
            assert metadata["skill_version"] == "1.0"
            assert metadata["provenance_source"] == metadata["source"]


def _read_call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="skills.read",
        arguments={"name": name},
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
