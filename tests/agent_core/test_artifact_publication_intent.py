import pytest
from agent_core.harness.task_contracts import AgentTaskType, infer_task_contract


@pytest.mark.parametrize("goal", [
    "生成柱状图，发布为 JSON artifact，再用 content.present 展示",
    "把图表发布为 artifact，展示示例数据",
    "Generate a chart and publish a JSON artifact",
    "Create the chart using files.publish",
    "用 files.publish content 分别发布以下两个 .vl.json 文件，再各自 content.present chart。",
    "Use files.publish to publish two .json files, then content.present chart.",
])
def test_artifact_publication_is_creation(goal):
    contract = infer_task_contract(goal)
    assert contract.task_type is AgentTaskType.CREATE
    assert contract.require_artifact
    assert not contract.require_verification


@pytest.mark.parametrize("goal", [
    "发布为 JSON artifact 并部署到服务器",
    "publish an artifact and deploy the service",
    "请发布新版本到生产环境",
    "用 files.publish content 发布以下两个 .vl.json 文件，然后部署到服务器。",
    "Use files.publish to publish two .json files and publish the release.",
    "请发布以下两个 .json 文件到网站。",
])
def test_external_operations_still_require_verification(goal):
    contract = infer_task_contract(goal)
    assert contract.task_type is AgentTaskType.OPERATE
    assert contract.require_verification


@pytest.mark.parametrize("has_artifact", [True, False])
def test_file_publication_completion_requires_a_real_tool_artifact(has_artifact):
    from agent_core.domain.modeling import ModelToolDefinition
    from agent_core.domain.tools import ToolCallStatus, ToolResult
    from agent_core.harness import (
        HarnessAttemptOutcome,
        HarnessLoop,
        HarnessModelStep,
        HarnessTask,
        SingleAttemptOrchestrator,
    )

    from tests.agent_core.test_sequential_tool_loop import (
        NOW,
        AllowAllPolicy,
        _completion,
        _gateway,
        _tool_call,
    )

    class Publications:
        def execute(self, call):
            return ToolResult(
                tool_call_id=call.tool_call_id, status=ToolCallStatus.EXECUTED,
                output='{"artifact_uri":"artifact://chart"}' if has_artifact else '{}',
            )

    goal = "用 files.publish content 发布以下两个 .vl.json 文件，再展示图表。"
    call = _tool_call("files.publish", {"content": "{}"}, "publish_chart")
    result = HarnessLoop().run(
        HarnessTask(title="Chart", user_input=goal, max_model_calls=2,
                    acceptance_contract=infer_task_contract(goal)),
        SingleAttemptOrchestrator(
            _gateway(_completion("Creating chart.", call), _completion("Chart created.")),
            AllowAllPolicy(), Publications(),
            model_step=HarnessModelStep(available_tools=(ModelToolDefinition(
                name="files.publish", description="Publish an Artifact.",
                parameters={"type": "object", "properties": {}},
            ),)), synthesize_tool_results=True,
        ).run, created_at=NOW,
    )
    assert result.attempt_result.outcome is (
        HarnessAttemptOutcome.COMPLETED if has_artifact else HarnessAttemptOutcome.SUSPENDED
    )
    delivery = result.attempt_result.metadata["delivery_assessment"]
    assert delivery["task_type"] == "create"
    assert delivery["unmet"] == ([] if has_artifact else ["required_artifact"])
