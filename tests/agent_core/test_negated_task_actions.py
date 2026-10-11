import pytest
from agent_core.harness.task_contracts import (
    AgentTaskType,
    infer_task_contract,
    parse_task_contract,
)


@pytest.mark.parametrize(
    "prompt",
    [
        "读取我的订阅源，查询最新一条内容。不修改订阅，不跳转页面。",
        "查询最新内容，不要修改订阅。",
        "Find the latest item. Do not change subscriptions.",
        "Find the latest item without changing subscriptions.",
        "查询最新内容，不要部署，不要删除数据。",
        "查询最新内容，第一页不是完整覆盖，不得把互相冲突的12%和8%增长结论去重删除。不要修改订阅或数据。",
        "查询最新内容，不要对订阅进行修改。",
        "查询最新内容，禁止将查询记录删除。",
    ],
)
def test_negated_actions_do_not_require_mutation_verification(prompt):
    contract = infer_task_contract(prompt)
    assert contract.task_type is AgentTaskType.RESEARCH
    assert not contract.require_verification


@pytest.mark.parametrize(
    "prompt",
    [
        "不要删除订阅，请修改订阅名称。",
        "Do not delete data. Please fix the parser.",
        "请修改订阅名称。",
        "不要删除订阅而是修改订阅名称。",
        "Do not delete data but please fix the parser.",
        "不得把冲突记录删除，并修改订阅名称。",
        "不要对订阅进行修改，但是请修复解析器。",
        "禁止将数据删除，然后修改名称。",
    ],
)
def test_positive_actions_still_require_verification(prompt):
    contract = infer_task_contract(prompt)
    assert contract.task_type is AgentTaskType.CHANGE
    assert contract.require_verification


@pytest.mark.parametrize("prompt,task_type,verification", [
    ("查询最新内容并给出来源链接，不修改订阅，不跳转页面。", AgentTaskType.RESEARCH, False),
    ("如何修改订阅？先不要执行。", AgentTaskType.ANSWER, False),
    ("请修改订阅名称，然后查询最新内容。", AgentTaskType.CHANGE, True),
    ("请发布报告并验证结果。", AgentTaskType.OPERATE, True),
    ("创建一个文件。", AgentTaskType.CREATE, False),
])
def test_partial_host_constraints_preserve_inferred_acceptance(prompt, task_type, verification):
    contract = parse_task_contract(
        {"goal": prompt, "requireEvidence": True, "requireCitations": True},
        fallback_goal=prompt,
    )
    assert contract.task_type is task_type
    assert contract.require_verification is verification
    assert contract.required_outcomes == infer_task_contract(prompt).required_outcomes
    assert contract.require_artifact == (task_type is AgentTaskType.CREATE)
    assert contract.require_evidence_reference and contract.require_matching_citation


def test_explicit_goal_not_appended_history_drives_partial_contract():
    goal = "查询最新内容并给出来源链接，不修改订阅。"
    contract = parse_task_contract(
        {"goal": goal, "requireEvidence": True, "requireCitations": True},
        fallback_goal=goal + "\nPrevious conversation context: 请发布报告，然后修改订阅。",
    )
    assert contract.task_type is AgentTaskType.RESEARCH
    assert not contract.require_verification
    assert "operation_completed" not in contract.required_outcomes
