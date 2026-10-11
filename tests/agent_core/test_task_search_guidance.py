from datetime import UTC, datetime

from agent_core.harness.model_step_support import task_acceptance_message
from agent_core.harness.task_contracts import AgentTaskType, TaskAcceptanceContract


def test_overview_uses_targeted_gaps_and_keeps_evidence_gate():
    message = task_acceptance_message("今天有什么值得关注的消息", created_at=datetime.now(UTC))
    assert message is not None
    assert "short candidate list" in message.content
    assert "sampling limits" in message.content
    assert "evidence_collected" in message.content
    assert "parallel-safe" in message.content and "verified findings" in message.content
    assert "Never bypass a policy denial" in message.content


def test_research_preserves_explicit_completeness_and_verification():
    contract = TaskAcceptanceContract(
        task_type=AgentTaskType.RESEARCH, goal="完整研究所有事件",
        require_evidence_reference=True, require_verification=True,
    )
    message = task_acceptance_message(
        contract.goal, contract=contract, created_at=datetime.now(UTC)
    )
    assert message is not None
    assert "requested research scope" in message.content
    assert "preserving required completeness" in message.content
    assert "short candidate list" not in message.content
    assert "verify the resulting state" in message.content
