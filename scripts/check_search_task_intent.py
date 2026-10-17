"""Assert factual lookups do not acquire an operation postcondition; no network/model."""

from agent_core.harness.task_contracts import (
    AgentTaskType,
    infer_task_contract,
    parse_task_contract,
)

LOOKUPS = (
    ("请联网核对 Node.js 22 和 Node.js 24 各自首次进入 LTS 的日期与代号，"
     "只采用官方来源并附链接，区分首次发布与进入 LTS，简明回答。"),
    "查询新版本什么时候发布，附来源链接",
    "核对历史部署记录并说明上线时间，附来源链接",
    "查找这次提交是谁发送的，附来源链接",
    "Look up when this version was published, with source links.",
    "Find out when the release was deployed, with source links.",
    "When was the first release published? Cite source links.",
)
ACTIONS = (
    "请核对后发布新版本到生产环境",
    "查询发布记录，然后发布新版本",
    "核对配置并部署服务",
    "查找问题再修复解析器",
    "查询状态，提交变更",
    "核对配置后发送邮件",
    "Look up the release date, then deploy the service.",
    "Find out the cause and fix the parser.",
    "查找发布记录。请发布新版本到生产环境",
    "查询历史发布时间并且发布新版本",
    "请执行一次测试，然后查询结果",
)


def main() -> None:
    for goal in LOOKUPS:
        for contract in (
            infer_task_contract(goal),
            parse_task_contract({"goal": goal, "requireEvidence": True}, fallback_goal=goal),
        ):
            assert not contract.require_verification, (goal, contract)
            assert contract.task_type is AgentTaskType.ANSWER, (goal, contract)
            assert contract.require_evidence_reference
            assert "operation_completed" not in contract.required_outcomes
            assert "result_verified" not in contract.required_outcomes
    for goal in ACTIONS:
        contract = infer_task_contract(goal)
        assert contract.task_type in {AgentTaskType.OPERATE, AgentTaskType.CHANGE}, (goal, contract)
        assert contract.require_verification, (goal, contract)
        assert "result_verified" in contract.required_outcomes
    goal = LOOKUPS[0]
    override = parse_task_contract(
        {"goal": goal, "taskType": "operate", "requireVerification": True}, fallback_goal=goal,
    )
    assert override.require_verification and override.task_type is AgentTaskType.OPERATE
    negated = infer_task_contract("查询发布记录，不要发布或部署。")
    assert not negated.require_verification
    print(f"PASS: {len(LOOKUPS)} factual lookups, {len(ACTIONS)} compound actions, "
          "Host override, negation")


if __name__ == "__main__":
    main()
