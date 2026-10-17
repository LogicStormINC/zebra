import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from agent_core.contracts.answer_events import AnswerCommittedPayload
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.harness.delivery_assessment import (
    RequestedVersionScope,
    _delivery_assessment,
    assess_version_scopes,
    qualify_version_scope,
    requested_version_scopes,
)
from agent_core.harness.orchestration_events import answer_committed_event
from agent_core.harness.task_contracts import infer_task_contract, parse_task_contract

URL = "https://example.org/docs/8-0/"


def receipt(url=URL, text="# Widget 8.0\nOriginal evidence", status="executed"):
    return {"tool_name": "web.fetch", "status": status, "output": text,
            "metadata": {"url": url}}


def completion(answer=f"Widget conclusion [source]({URL})"):
    return ModelCompletion(assistant_message=SessionMessage(
        message_id=new_message_id(), role=MessageRole.ASSISTANT, content=answer,
        created_at=datetime.now(UTC), provider_reasoning_content="retained continuation",
    ))


def delivery():
    return _delivery_assessment(
        "complete", satisfied=("answer_present", "task_acceptance_contract"))


def test_requested_literal_scope_and_host_override_do_not_invent_minor_versions():
    contract = infer_task_contract("请用官方来源核对 PostgreSQL 18 和 Redis 8 的能力")
    assert [(s.subject, s.version) for s in contract.version_scopes] == [
        ("PostgreSQL", "18"), ("Redis", "8")]
    assert requested_version_scopes("Widget v8.0 Widget 8.x") == (
        RequestedVersionScope("Widget", "8.0"), RequestedVersionScope("Widget", "8.x"))
    assert not infer_task_contract("只回复 Widget 8 接入完毕，不要核查").version_scopes
    explicit = parse_task_contract({"versionScopes": [{"subject": "Widget", "version": "8.0"}]},
                                   fallback_goal="核对 Widget 8，提供来源")
    assert explicit.version_scopes == (RequestedVersionScope("Widget", "8.0"),)
    disabled = parse_task_contract({"versionScopes": []}, fallback_goal=contract.goal)
    assert disabled.version_scopes == ()
    for bad in [{"versionScopes": "8"}, {"versionScopes": ["8"]},
                {"versionScopes": [{"subject": "x" * 100, "version": "8"}]}]:
        with pytest.raises(ValueError):
            parse_task_contract(bad, fallback_goal=contract.goal)


def test_narrow_minor_scope_cannot_prove_major_scope_and_preserves_original_evidence():
    contract = infer_task_contract("核对 Widget 8，提供来源")
    original = completion()
    source = receipt()
    before = json.dumps(source)
    revised, assessment = qualify_version_scope(original, delivery(), contract, [source])
    report = assessment["version_scope"]
    assert assessment["status"] == "partial"
    assert assessment["unmet"] == ["version_scope_unresolved"]
    assert "task_acceptance_contract" not in assessment["satisfied"]
    assert report["checked_scope"][0]["versions"] == ["8.0"]
    assert report["requested_scope"][0]["version"] == "8"
    assert report["unresolved_points"][0]["subject"] == "Widget"
    assert report["semantic_coverage_certified"] is False
    assert "部分覆盖" in revised.assistant_message.content
    assert original.assistant_message.content == f"Widget conclusion [source]({URL})"
    assert revised.assistant_message.message_id == original.assistant_message.message_id
    assert revised.assistant_message.provider_reasoning_content == "retained continuation"
    assert json.dumps(source) == before


def test_equal_scope_matches_source_version_only_not_semantic_completeness():
    contract = infer_task_contract("核对 Widget 8.0，提供来源")
    original = completion()
    revised, assessment = qualify_version_scope(original, delivery(), contract, [receipt()])
    assert revised is original
    assert assessment["status"] == "complete"
    assert assessment["version_scope"]["status"] == "matched"
    assert assessment["version_scope"]["semantic_coverage_certified"] is False


def test_unknown_uncited_failed_search_only_and_mismatched_titles_do_not_count():
    requested = (RequestedVersionScope("Widget", "8.0"),)
    for source in [receipt(status="failed"), receipt(url="https://example.org/latest/"),
                   receipt(text="# Other 8.0"), receipt(text="# Widget 8.8"),
                   {**receipt(), "tool_name": "web.search"}]:
        report = assess_version_scopes(
            requested, f"[source]({source['metadata']['url']})", [source])
        assert report["checked_scope"][0]["versions"] == []
        assert report["status"] == "partial"
    assert assess_version_scopes(requested, "no citation", [receipt()])["status"] == "partial"
    # Repeating source 8.0 or adding 8.8 does not establish the entire 8.x series.
    report = assess_version_scopes((RequestedVersionScope("Widget", "8"),),
                                  f"{URL} https://example.org/docs/8-8/",
                                  [receipt(), receipt(), receipt(
                                      url="https://example.org/docs/8-8/", text="# Widget 8.8")])
    assert report["checked_scope"][0]["versions"] == ["8.0", "8.8"]
    assert report["status"] == "partial"


def test_public_qualification_preserves_json_and_hard_length_contracts():
    contract = infer_task_contract("核对 Widget 8，提供来源")
    for original, bound in [(completion(json.dumps({"answer": "value"})), None),
                            (completion(), len(completion().assistant_message.content))]:
        revised, assessment = qualify_version_scope(
            original, delivery(), replace(contract, max_characters=bound), [receipt()])
        assert revised is original
        assert assessment["status"] == "partial"
    plain = completion("done")
    unchanged, _ = qualify_version_scope(plain, delivery(), infer_task_contract("回复 done"), [])
    assert unchanged is plain


def test_committed_event_accepts_bounded_scope_and_rejects_false_complete():
    original = completion()
    revised, assessment = qualify_version_scope(
        original, delivery(), infer_task_contract("核对 Widget 8，提供来源"), [receipt()])
    draft = answer_committed_event(revised, attempt_number=1, delivery_assessment=assessment)
    parsed = AnswerCommittedPayload.model_validate(draft.payload)
    assert parsed.delivery_assessment.status == "partial"
    assert parsed.delivery_assessment.version_scope.unresolved_points
    forged = {**draft.payload, "delivery_assessment": {**assessment, "status": "complete"}}
    with pytest.raises(ValueError, match="unresolved version scope"):
        AnswerCommittedPayload.model_validate(forged)
    assert AnswerCommittedPayload.model_validate({
        "attempt_number": 1, "assistant_message": "old answer",
        "delivery_assessment": {"status": "complete"},
    }).delivery_assessment.version_scope is None


def test_real_harness_commits_partial_without_extra_model_round_or_tool():
    from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
    from agent_core.domain.events import EventType
    from agent_core.domain.identifiers import new_tool_call_id
    from agent_core.domain.modeling import ModelToolDefinition
    from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
    from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
    from agent_core.harness import (
        HarnessAttemptOutcome,
        HarnessLoop,
        HarnessModelStep,
        HarnessTask,
        SingleAttemptOrchestrator,
    )

    class Policy:
        def evaluate_tool_call(self, _call):
            return PolicyDecision(decision=PolicyDecisionType.ALLOW, reason="test",
                                  policy_profile="test")

    class Tools:
        def execute(self, call):
            return ToolResult(tool_call_id=call.tool_call_id, status=ToolCallStatus.EXECUTED,
                              output="# Widget 8.0\nEvidence", metadata={"url": URL})

    call = ToolCall(tool_call_id=new_tool_call_id(), name="web.fetch", arguments={"url": URL},
                    created_at=datetime.now(UTC), provider_call_id="fetch")
    first = replace(completion("read"), tool_calls=(call,))
    final = completion()
    gateway = ScriptedModelGateway(responses=(ScriptedModelResponse(completion=first),
                                              ScriptedModelResponse(completion=final)))
    contract = infer_task_contract("核对 Widget 8，提供来源")
    orchestrator = SingleAttemptOrchestrator(
        gateway, Policy(), Tools(), model_step=HarnessModelStep(available_tools=(
            ModelToolDefinition(name="web.fetch", description="Fetch",
                                parameters={"type": "object", "properties": {}}),
        )), synthesize_tool_results=True,
    )
    result = HarnessLoop().run(HarnessTask(title="scope", user_input=contract.goal,
                                         acceptance_contract=contract), orchestrator.run)
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert len(gateway.requests) == 2
    event = next(e for e in result.events if e.event_type is EventType.ANSWER_COMMITTED)
    parsed = AnswerCommittedPayload.model_validate(event.payload)
    assert parsed.delivery_assessment.status == "partial"
    assert "部分覆盖" in parsed.assistant_message
    assert result.attempt_result.metadata["delivery_assessment"]["status"] == "partial"
