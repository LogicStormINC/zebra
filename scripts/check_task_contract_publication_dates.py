"""Release-date questions keep evidence gates without inventing a publish action."""

from agent_core.harness.task_contracts import AgentTaskType, infer_task_contract

for prompt in (
    "请联网搜索并核对 PostgreSQL 18、Redis 8 的正式发布日期和各两项主要新特性，"
    "只采用官方来源并附链接，简明回答。",
    "搜索软件正式发布日期，给出官方来源和链接。",
    "核对新版发布时间，给出官方来源和链接。",
):
    contract = infer_task_contract(prompt)
    assert contract.task_type not in {AgentTaskType.OPERATE, AgentTaskType.CHANGE}, prompt
    assert not contract.require_verification, prompt
    assert contract.require_evidence_reference and contract.require_matching_citation, prompt
    assert "operation_completed" not in contract.required_outcomes, prompt

for prompt in (
    "请发布新版本",
    "发布新版本",
    "请发布发布日期到公告",
    "帮我发布日期到公告",
    "开始发布日期到公告",
    "核对发布日期，然后发布新版本",
    "核对发布时间，并部署新版本",
    "please publish the release date",
    "please deploy the new version",
):
    contract = infer_task_contract(prompt)
    assert contract.task_type is AgentTaskType.OPERATE, prompt
    assert contract.require_verification, prompt
    assert {"operation_completed", "result_verified"} <= set(contract.required_outcomes), prompt

print("12 noun/action checks passed; evidence and real-action verification retained")
