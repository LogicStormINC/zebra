from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_subagent_id
from agent_core.domain.subagents import (
    ResearchSource,
    ResearchSubagentResult,
    ResearchSubagentTask,
    SubagentStatus,
)


def test_research_task_requires_absolute_workspace_and_positive_budgets() -> None:
    with pytest.raises(ValueError, match="absolute"):
        ResearchSubagentTask(objective="Inspect evidence", workspace_root=Path("."))

    with pytest.raises(ValueError, match="budgets"):
        ResearchSubagentTask(
            objective="Inspect evidence",
            workspace_root=Path("/").resolve(),
            max_model_calls=0,
        )


def test_research_result_validates_sources_and_confidence() -> None:
    source = ResearchSource(reference="README.md", kind="files.read")
    result = ResearchSubagentResult(
        subagent_id=new_subagent_id(),
        status=SubagentStatus.COMPLETED,
        summary="Evidence found.",
        sources=(source,),
        confidence=1.0,
        model_calls_used=2,
        tool_calls_used=1,
    )

    assert result.sources == (source,)
    with pytest.raises(ValueError, match="confidence"):
        ResearchSubagentResult(
            subagent_id=new_subagent_id(),
            status=SubagentStatus.COMPLETED,
            summary="Invalid confidence.",
            confidence=1.1,
        )
