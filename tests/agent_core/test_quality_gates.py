from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.verification_evidence import VerificationResourceRef
from agent_core.harness.evidence_ledger import EvidenceLedger
from agent_core.harness.final_completion import (
    _contract_verification_satisfied,
    _quality_revision_feedback,
)
from agent_core.harness.models import SkillReadRequirement
from agent_core.harness.quality_gates import evaluate_answer, missing_selected_skills
from agent_core.harness.task_contracts import (
    AgentTaskType,
    TaskAcceptanceContract,
    infer_task_contract,
    parse_task_contract,
)
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


def test_explicit_maximum_length_is_inferred_and_enforced() -> None:
    chinese = infer_task_contract("请在不超过180字内回答")
    english = infer_task_contract("Answer in no more than 180 Chinese characters")

    assert chinese.max_characters == 180
    assert english.max_characters == 180
    too_long = evaluate_answer("请在不超过5字内回答", "这个回答明显太长")
    assert too_long.reason == "deliverable_too_long"
    assert too_long.missing_requirements == ("maximum_length:5_characters",)


def test_information_request_does_not_become_mutation_authority() -> None:
    assert infer_task_contract("解释如何部署这个服务").task_type is AgentTaskType.ANSWER
    assert infer_task_contract("Please explain how to deploy it").task_type is AgentTaskType.ANSWER
    assert infer_task_contract("请部署这个服务").task_type is AgentTaskType.OPERATE


def test_host_contract_can_require_goal_terms_and_response_bound() -> None:
    contract = parse_task_contract(
        {
            "taskType": "answer",
            "requiredAnswerTerms": ["PostgreSQL", "Event Store"],
            "maxCharacters": 80,
        },
        fallback_goal="Explain the authority boundary.",
    )

    missing = evaluate_answer("Explain it.", "PostgreSQL is authoritative.", contract=contract)
    assert missing.reason == "deliverable_missed_goal"
    assert missing.missing_requirements == ("required_answer_term:Event Store",)
    assert evaluate_answer(
        "Explain it.",
        "PostgreSQL stores the authoritative Event Store.",
        contract=contract,
    ).passed


def test_english_markers_require_word_boundaries() -> None:
    assert evaluate_answer("NEW CONCURRENT FOLLOW-UP", "NEW TURN ANSWER").passed


def test_current_analysis_requires_collected_and_matching_source_reference() -> None:
    prompt = "最近国际形势有什么变化"
    answer = "# 变化\n\n- 已发生重要变化。\n\n" + "具体分析。" * 40
    no_evidence = evaluate_answer(prompt, answer)
    assert not no_evidence.passed
    assert "verified_evidence" in no_evidence.missing_requirements

    ledger = EvidenceLedger(
        successful_tool_results=1,
        evidence_refs=("https://example.test/source",),
    )
    uncited = evaluate_answer(prompt, answer, evidence=ledger)
    assert not uncited.passed
    assert "citation_matching_collected_evidence" in uncited.missing_requirements

    cited = evaluate_answer(
        prompt,
        f"{answer}\n\n来源：https://example.test/source",
        evidence=ledger,
    )
    assert cited.passed


def test_length_revision_feedback_preserves_a_matching_local_reference() -> None:
    path = "packages/agent-storage/src/agent_storage/composition.py"
    answer = f"{'x' * 200} `{path}`"

    feedback = _quality_revision_feedback(
        answer=answer,
        reason="deliverable_too_long",
        missing_requirements=("maximum_length:180_characters",),
        evidence=EvidenceLedger(successful_tool_results=1, evidence_refs=(path,)),
    )

    assert "remove nonessential prose and duplicate references" in feedback
    assert f"Keep this exact collected reference unchanged: {path}." in feedback


def test_citation_gate_rejects_invented_and_annotation_extended_urls() -> None:
    prompt = "请总结最近变化并附链接"
    source = "https://example.test/items/42"
    ledger = EvidenceLedger(successful_tool_results=1, evidence_refs=(source,))
    body = "# 变化\n\n- 关键事实与分析。\n\n" + "补充说明。" * 40

    invented = evaluate_answer(
        prompt,
        f"{body}\n\n[原文](https://example.test/items/99)",
        evidence=ledger,
    )
    assert not invented.passed
    assert "citation_uses_exact_collected_url" in invented.missing_requirements

    extended = evaluate_answer(
        prompt,
        f"{body}\n\n[原文]({source}（补充说明）)",
        evidence=ledger,
    )
    assert not extended.passed
    assert "citation_uses_exact_collected_url" in extended.missing_requirements

    exact = evaluate_answer(prompt, f"{body}\n\n[原文]({source})（补充说明）", evidence=ledger)
    assert exact.passed


def test_claimed_evidence_text_does_not_substitute_for_a_real_ledger() -> None:
    result = evaluate_answer("请提供证据", "证据：我猜的。")
    assert not result.passed
    assert result.reason == "deliverable_missing_evidence"


def test_explicit_host_contract_overrides_prompt_heuristics() -> None:
    contract = parse_task_contract(
        {
            "taskType": "change",
            "goal": "Update the configuration and prove it worked.",
            "requiredOutcomes": ["change_applied", "result_verified"],
            "requireEvidence": True,
            "requireVerification": True,
        },
        fallback_goal="Do it.",
    )

    assert contract.task_type is AgentTaskType.CHANGE
    assert contract.require_verification
    assert contract.required_outcomes == ("change_applied", "result_verified")
    assert not evaluate_answer("Do it.", "Done.", contract=contract).passed


def test_explicit_artifact_contract_requires_a_real_artifact_reference() -> None:
    contract = TaskAcceptanceContract(
        task_type=AgentTaskType.CREATE,
        goal="Create the report artifact.",
        require_artifact=True,
    )
    missing = evaluate_answer("Create it.", "Created.", contract=contract)
    assert "required_artifact" in missing.missing_requirements
    ledger = EvidenceLedger(artifact_refs=("artifact://report",))
    assert evaluate_answer("Create it.", "Created.", contract=contract, evidence=ledger).passed


def test_inferred_task_contracts_require_type_specific_delivery_outcomes() -> None:
    change = infer_task_contract("修复配置并验证")
    create = infer_task_contract("创建一份报告文件")
    operate = infer_task_contract("部署当前版本")

    assert change.required_outcomes == (
        "answer_present",
        "evidence_collected",
        "change_applied",
        "result_verified",
    )
    assert create.required_outcomes == ("answer_present", "artifact_produced")
    assert create.require_artifact
    assert operate.required_outcomes == (
        "answer_present",
        "evidence_collected",
        "operation_completed",
        "result_verified",
    )


def test_scheduled_job_is_an_operation_not_an_artifact_creation() -> None:
    contract = infer_task_contract("Create the requested scheduled job exactly once and verify it")

    assert contract.task_type is AgentTaskType.OPERATE
    assert contract.require_verification
    assert not contract.require_artifact


def test_task_contract_verification_needs_runtime_proof() -> None:
    assert not _contract_verification_satisfied({}, read_only_tools=frozenset())
    assert _contract_verification_satisfied(
        {"tool_metadata": {"postcondition_met": True}},
        read_only_tools=frozenset(),
    )
    assert not _contract_verification_satisfied(
        {"verification_passed": True, "verification_summary": "verifier hook skipped"},
        read_only_tools=frozenset(),
    )


def test_resource_scoped_mutation_requires_matching_fresh_read() -> None:
    now = datetime.now(UTC)
    mutation = ToolCall(
        tool_call_id=uuid4(),
        name="sources.resume",
        arguments={"source_id": "src_a"},
        created_at=now,
    )
    read_a = ToolCall(
        tool_call_id=uuid4(),
        name="sources.get_status",
        arguments={"source_id": "src_a"},
        created_at=now,
    )
    read_b = ToolCall(
        tool_call_id=uuid4(),
        name="sources.get_status",
        arguments={"source_id": "src_b"},
        created_at=now,
    )
    result = ToolResult(
        tool_call_id=mutation.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="ok",
    )
    metadata = record_tool_freshness(
        {},
        mutation,
        result,
        read_only_tools=frozenset({"sources.get_status"}),
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
    read = mutation.model_copy(update={"tool_call_id": uuid4(), "name": "sources.get_status"})
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
