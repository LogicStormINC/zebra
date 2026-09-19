from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.verification_evidence import VerificationResourceRef
from agent_core.harness.models import SkillReadRequirement
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


def test_selected_skill_requires_the_frozen_version_and_digest() -> None:
    requirement = SkillReadRequirement(
        component="skill-1",
        skill_id="skill-1",
        version_id="version-2",
        digest="b" * 64,
    )
    stale = {
        "skill_reads": {
            "skill-1": {
                "skill_id": "skill-1",
                "skill_version_id": "version-1",
                "skill_digest": "a" * 64,
            }
        }
    }
    assert missing_selected_skills(("skill-1",), stale, (requirement,)) == ("skill-1",)

    exact = {
        "skill_reads": {
            "skill-1": {
                "skill_id": "skill-1",
                "skill_version_id": "version-2",
                "skill_digest": "b" * 64,
            }
        }
    }
    assert missing_selected_skills(("skill-1",), exact, (requirement,)) == ()


def test_analysis_word_alone_does_not_force_a_long_form_answer() -> None:
    assert evaluate_answer("分析一下原因", "根因是配置缺失。建议补齐配置后重试。").passed


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


def test_concurrent_read_cannot_verify_a_mutation_from_the_same_batch() -> None:
    now = datetime.now(UTC)
    mutation = ToolCall(
        tool_call_id=uuid4(),
        name="sources.resume",
        arguments={"source_id": "src_a"},
        created_at=now,
    )
    read = ToolCall(
        tool_call_id=uuid4(),
        name="sources.get_status",
        arguments={"source_id": "src_a"},
        created_at=now,
    )
    executed = ToolResult(
        tool_call_id=mutation.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="ok",
    )
    metadata = record_tool_freshness(
        {},
        mutation,
        executed,
        read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
    )

    metadata = record_tool_freshness(
        metadata,
        read,
        executed.model_copy(update={"tool_call_id": read.tool_call_id}),
        read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
        observed_epoch=0,
    )

    assert metadata["verified_resource_epochs"] == {"source_id:src_a": 0}
    assert needs_post_mutation_verification(
        metadata,
        read_only_tools=frozenset({"sources.get_status"}),
    )


def test_explicit_resource_identity_prevents_cross_namespace_verification() -> None:
    now = datetime.now(UTC)
    mutation = ToolCall(
        tool_call_id=uuid4(),
        name="sources.resume",
        arguments={"source_id": "same-id"},
        created_at=now,
    )
    read = mutation.model_copy(
        update={"tool_call_id": uuid4(), "name": "sources.get_status"}
    )
    resource_a = VerificationResourceRef(
        authority_issuer="https://issuer.example.com",
        namespace_id="tenant-a",
        host_app_id="trench",
        resource_type="source",
        resource_id="same-id",
    )
    resource_b = resource_a.model_copy(update={"namespace_id": "tenant-b"})

    def result(
        call: ToolCall,
        resource: VerificationResourceRef,
        **extra: object,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
            metadata={
                "route": "host_tool_gateway",
                "verification_resource_ref": resource.model_dump(mode="json"),
                **extra,
            },
        )

    metadata = record_tool_freshness(
        {},
        mutation,
        result(mutation, resource_a),
        read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
    )
    metadata = record_tool_freshness(
        metadata,
        read,
        result(read, resource_b),
        read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
    )
    assert needs_post_mutation_verification(
        metadata, read_only_tools=frozenset({"sources.get_status"})
    )

    metadata = record_tool_freshness(
        metadata,
        read,
        result(read, resource_a),
        read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
    )
    assert not needs_post_mutation_verification(
        metadata, read_only_tools=frozenset({"sources.get_status"})
    )
    assert metadata["verification_evidence"][-1]["verification_status"] == "verified"

    versioned = record_tool_freshness(
        {},
        mutation,
        result(mutation, resource_a, commit_version="revision-2"),
        read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
    )
    versioned = record_tool_freshness(
        versioned,
        read,
        result(read, resource_a, read_version="revision-1"),
        read_only_tools=frozenset({"sources.get_status"}),
        mutation_tools=frozenset({"sources.resume"}),
    )
    assert versioned["verification_evidence"][-1]["verification_status"] == "unverified"
    assert needs_post_mutation_verification(
        versioned, read_only_tools=frozenset({"sources.get_status"})
    )
