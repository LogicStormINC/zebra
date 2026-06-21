from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
)
from agent_core.ports.context_compiler import RuntimeEvidenceInput


class RecordingContextCompiler:
    def __init__(self) -> None:
        self.calls: list[tuple[RuntimeEvidenceInput, ...]] = []

    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
    ) -> str | None:
        self.calls.append(runtime_evidence)
        return f"evidence={len(runtime_evidence)}"


class RecordingModelGateway:
    def __init__(self) -> None:
        self.requests: list[tuple[SessionMessage, ...]] = []

    def complete(self, messages: list[SessionMessage]) -> ModelCompletion:
        self.requests.append(tuple(messages))
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="captured",
                created_at=datetime(2026, 6, 22, 13, 0, tzinfo=UTC),
            )
        )


def test_retry_attempt_receives_prior_runtime_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    compiler = RecordingContextCompiler()
    gateway = RecordingModelGateway()
    model_step = HarnessModelStep(context_compiler=compiler)
    seen_evidence_sizes: list[int] = []

    def attempt_runner(context: HarnessContext) -> HarnessAttemptResult:
        seen_evidence_sizes.append(len(context.task.runtime_evidence))
        if context.attempt.number == 1:
            return HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="first attempt failed",
                metadata={
                    "plan_summary": "inspect failing path",
                    "plan_metadata": {"source": "planner"},
                    "tool_name": "tests.run",
                    "tool_status": "failed",
                    "tool_output": "2 failed",
                    "tool_metadata": {"artifact_uri": "artifact://tests/1"},
                    "verification_summary": "smoke tests failed",
                    "verification_passed": False,
                    "verification_metadata": {"suite": "smoke"},
                    "tool_calls_executed": 1,
                    "model_calls_used": 1,
                },
            )
        model_step.request_initial_completion(
            context.task,
            gateway,
            created_at=datetime(2026, 6, 22, 13, 0, tzinfo=UTC),
        )
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="second attempt completed",
            metadata={"model_calls_used": 1, "tool_calls_executed": 0},
        )

    HarnessLoop().run(
        HarnessTask(
            title="Retry task",
            user_input="Fix the failing tests.",
            max_attempts=2,
            workspace_root=workspace.resolve(),
        ),
        attempt_runner,
        created_at=datetime(2026, 6, 22, 12, 55, tzinfo=UTC),
    )

    assert seen_evidence_sizes == [0, 5]
    assert len(compiler.calls) == 1
    assert [evidence.kind for evidence in compiler.calls[0]] == [
        "conversation_summary",
        "planner_summary",
        "verifier_summary",
        "tool_status",
        "tool_output_summary",
    ]
