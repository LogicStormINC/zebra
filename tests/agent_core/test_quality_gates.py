from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.quality_gates import evaluate_answer, missing_selected_skills
from agent_core.harness.tool_freshness import (
    can_refresh_repeated_read,
    needs_post_mutation_verification,
    record_tool_freshness,
)


def test_substantive_answer_gate_requires_structure_and_detail() -> None:
    short = evaluate_answer("请生成一篇 markdown 格式的报告", "结论很简单。")
    assert not short.passed
    assert short.reason == "deliverable_too_shallow"

    answer = "# 结论\n\n- 证据\n\n## 分析\n\n" + "证据与分析。" * 60
    assert evaluate_answer("请生成一篇 markdown 格式的报告", answer).passed


def test_selected_skills_are_matched_by_component_or_skill_id() -> None:
    assert missing_selected_skills(("skill-1", "writing"), {"skill_reads": {"skill-1": "d"}}) == (
        "writing",
    )


def test_resource_scoped_mutation_requires_matching_fresh_read() -> None:
    now = datetime.now(UTC)
    mutation = ToolCall(
        tool_call_id=uuid4(), name="sources.resume",
        arguments={"source_id": "src_a"}, created_at=now,
    )
    read_a = ToolCall(
        tool_call_id=uuid4(), name="sources.get_status",
        arguments={"source_id": "src_a"}, created_at=now,
    )
    read_b = ToolCall(
        tool_call_id=uuid4(), name="sources.get_status",
        arguments={"source_id": "src_b"}, created_at=now,
    )
    result = ToolResult(
        tool_call_id=mutation.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="ok",
    )
    metadata = record_tool_freshness(
        {}, mutation, result, read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
    )
    read_tools = frozenset({"sources.get_status"})
    assert can_refresh_repeated_read(read_a, metadata=metadata, read_only_tools=read_tools)
    assert not can_refresh_repeated_read(read_b, metadata=metadata, read_only_tools=read_tools)
    assert needs_post_mutation_verification(metadata, read_only_tools=read_tools)
