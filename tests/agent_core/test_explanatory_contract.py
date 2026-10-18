"""Explanations mention mutations without requesting them; compound actions still verify."""
import pytest
from agent_core.harness.task_contracts import (
    AgentTaskType,
    infer_task_contract,
    parse_task_contract,
)

EXPLANATIONS = (
    "请用中文简要说明数据库主键和外键的区别，用订单与用户表举例，并说明删除用户时应考虑什么。约300字，无需联网。",
    "说明删除用户时的注意事项",
    "请说明删除记录与软删除的区别",
    "说明如何修复配置错误，不要修改任何文件",
    "说明部署服务、发送邮件和提交变更的风险",
)
ACTIONS = (
    "删除用户，并说明结果",
    "请删除用户，然后说明结果",
    "说明原因，并修复配置错误",
    "先说明风险，然后删除用户",
    "说明后修改配置",
    "修改配置并说明修改后的行为",
    "说明风险，并部署服务",
    "说明结果，再提交变更",
)


@pytest.mark.parametrize("goal", EXPLANATIONS)
def test_explanation_does_not_require_changes(goal):
    contracts = (infer_task_contract(goal), parse_task_contract({"goal": goal}, fallback_goal=goal))
    for contract in contracts:
        assert contract.task_type is AgentTaskType.ANSWER
        assert not contract.require_verification
        assert "change_applied" not in contract.required_outcomes
        assert "result_verified" not in contract.required_outcomes


@pytest.mark.parametrize("goal", ACTIONS)
def test_real_and_compound_actions_still_require_verification(goal):
    contract = infer_task_contract(goal)
    assert contract.task_type in {AgentTaskType.CHANGE, AgentTaskType.OPERATE}
    assert contract.require_verification
    assert "result_verified" in contract.required_outcomes


def test_explicit_host_change_contract_remains_authoritative():
    goal = EXPLANATIONS[0]
    contract = parse_task_contract(
        {"goal": goal, "taskType": "change", "requireVerification": True}, fallback_goal=goal,
    )
    assert contract.task_type is AgentTaskType.CHANGE
    assert contract.require_verification
