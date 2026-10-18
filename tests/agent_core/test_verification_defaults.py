"""Verification defaults and observed freshness cannot depend on read capability."""
import pytest
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.final_completion import _contract_verification_satisfied
from agent_core.harness.task_contracts import AgentTaskType, parse_task_contract
from agent_core.harness.tool_freshness import needs_post_mutation_verification
from test_sequential_tool_loop import (
    NOW,
    TOOLS,
    AllowAllPolicy,
    MutationOnlyToolGateway,
    _completion,
    _gateway,
    _tool_call,
)


@pytest.mark.parametrize("name", ["taskType", "task_type"])
@pytest.mark.parametrize("kind,outcome", [
    ("change", "change_applied"), ("operate", "operation_completed"),
])
@pytest.mark.parametrize("goal", ["解释配置含义", "修改配置", "部署服务"])
def test_missing_fields_follow_final_mutation_type(name, kind, outcome, goal):
    contract = parse_task_contract({name: kind}, fallback_goal=goal)
    assert contract.task_type is AgentTaskType(kind)
    assert contract.require_verification
    assert outcome in contract.required_outcomes and "result_verified" in contract.required_outcomes
    other = "operation_completed" if kind == "change" else "change_applied"
    assert other not in contract.required_outcomes


def test_explicit_host_fields_are_preserved_but_cannot_verify_an_observed_mutation():
    contract = parse_task_contract(
        {"taskType": "change", "requireVerification": False,
         "requiredOutcomes": ["answer_present"]}, fallback_goal="解释配置",
    )
    assert not contract.require_verification
    assert contract.required_outcomes == ("answer_present",)
    assert needs_post_mutation_verification({"mutation_epoch": 1}, read_only_tools=frozenset())
    answer = parse_task_contract({"goal": "说明删除用户时的注意事项"}, fallback_goal="说明配置")
    assert answer.task_type is AgentTaskType.ANSWER and not answer.require_verification


@pytest.mark.parametrize("tools", [frozenset(), frozenset({"files.read"})])
@pytest.mark.parametrize("metadata,needed", [
    ({}, False),
    ({"mutation_epoch": 1}, True),
    ({"mutation_epoch": 2, "verified_mutation_epoch": 1}, True),
    ({"mutation_epoch": 2, "verified_mutation_epoch": 2}, False),
    ({"mutation_epoch": 2, "verified_mutation_epoch": 2,
      "mutation_resource_epochs": {"a": 1, "b": 2}, "verified_resource_epochs": {"a": 1}}, True),
    ({"mutation_epoch": 2, "mutation_resource_epochs": {"a": 1, "b": 2},
      "verified_resource_epochs": {"a": 1, "b": 2}}, False),
])
def test_freshness_uses_evidence_even_without_read_capability(tools, metadata, needed):
    assert needs_post_mutation_verification(metadata, read_only_tools=tools) is needed
    if metadata.get("mutation_epoch"):
        assert _contract_verification_satisfied(metadata, read_only_tools=tools) is not needed


def test_explicit_postcondition_receipt_without_mutation_epoch_still_counts():
    assert _contract_verification_satisfied(
        {"tool_metadata": {"postcondition_met": True}}, read_only_tools=frozenset(),
    )


@pytest.mark.parametrize("tool_limit", [1, 3])
@pytest.mark.parametrize("explicit_contract", [False, True])
def test_mutation_without_read_tools_suspends_without_extra_model_or_tool_round(
    tool_limit, explicit_contract,
):
    mutation = _tool_call("tests.run", {"preset": "mutate"}, "one-write")
    gateway = _gateway(_completion("Apply change.", mutation), _completion("Done."))
    tools = MutationOnlyToolGateway()
    result = HarnessLoop().run(
        HarnessTask(title="Verify missing capability", user_input="Change the state.",
                    max_model_calls=4, max_tool_calls=tool_limit,
                    acceptance_contract=(parse_task_contract({"taskType": "change"},
                                                            fallback_goal="Change the state.")
                                         if explicit_contract else None)),
        SingleAttemptOrchestrator(gateway, AllowAllPolicy(), tools,
                                  model_step=HarnessModelStep(available_tools=TOOLS),
                                  synthesize_tool_results=True).run,
        created_at=NOW,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "verification_required"
    assert result.attempt_result.metadata["unverified_mutation"] is True
    assert result.run_result.model_calls_used == 2 and len(tools.calls) == 1
