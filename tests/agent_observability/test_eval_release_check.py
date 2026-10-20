import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessTask, SingleAttemptOrchestrator
from agent_observability import load_eval_cases

from scripts.eval_release_check import (
    _AllowAllPolicy,
    _completion,
    _EvalToolGateway,
    _execute_replay,
)


def test_eval_release_check_passes_baseline_dataset() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/eval_release_check.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "eval release gate: passed=True" in result.stdout
    assert "cases=30" in result.stdout


def test_mutating_replay_verifies_the_changed_state() -> None:
    case = next(
        case
        for case in load_eval_cases(Path("evals/cases"))
        if case.case_id == "bugfix-python-test"
    )
    replay, trace = _execute_replay(case)

    assert replay.terminal_outcome == "completed"
    assert replay.delivery_status == "complete"
    events = trace["events"]
    calls = [
        event["payload"]["tool_name"]
        for event in events
        if event["event_type"] == "tool_execution_started"
    ]
    assert calls == ["eval.mutate", "eval.observe"]
    results = [
        event["payload"] for event in events if event["event_type"] == "tool_execution_completed"
    ]
    assert [result["metadata"]["revision"] for result in results] == [1, 1]


@pytest.mark.parametrize(
    ("names", "fail_read", "expected"),
    [
        (("eval.mutate",), False, "suspended"),
        (("eval.observe", "eval.mutate"), False, "suspended"),
        (("eval.mutate", "eval.observe"), True, "suspended"),
        (("eval.mutate", "eval.observe"), False, "completed"),
    ],
)
def test_eval_tools_require_successful_later_verification(
    names: tuple[str, ...],
    fail_read: bool,
    expected: str,
) -> None:
    case = next(
        case
        for case in load_eval_cases(Path("evals/cases"))
        if case.case_id == "bugfix-python-test"
    )
    now = datetime(2026, 9, 20, tzinfo=UTC)

    class Gateway(_EvalToolGateway):
        def execute(self, tool_call: ToolCall) -> ToolResult:
            if fail_read and tool_call.name == "eval.observe":
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    status=ToolCallStatus.FAILED,
                    output="deterministic read failed",
                )
            return super().execute(tool_call)

    calls = tuple(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name=name,
            arguments={"case_id": case.case_id, "step": index + 1},
            created_at=now,
        )
        for index, name in enumerate(names)
    )
    responses = tuple(
        ScriptedModelResponse(
            completion=_completion(
                "Execute deterministic step.",
                created_at=now,
                tool_call=call,
            )
        )
        for call in calls
    ) + (
        ScriptedModelResponse(
            completion=_completion(
                "The deterministic scenario completed.",
                created_at=now,
            )
        ),
    )
    run = HarnessLoop().run(
        HarnessTask(
            title=case.title,
            user_input=case.prompt,
            max_model_calls=len(responses),
            max_tool_calls=len(calls),
        ),
        SingleAttemptOrchestrator(
            ScriptedModelGateway(responses=responses),
            _AllowAllPolicy(),
            Gateway(case),
            synthesize_tool_results=True,
        ).run,
        created_at=now,
    )

    assert run.attempt_result.outcome.value == expected
    if expected == "suspended":
        assert run.attempt_result.metadata["stop_reason"] == "verification_required"
        assert run.attempt_result.metadata["unverified_mutation"] is True
