import json

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.model_step_support import tool_result_content


def test_structured_metadata_reaches_the_model_without_secrets() -> None:
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="",
        metadata={
            "artifact_uri": "artifact://report-1",
            "result_count": 3,
            "authorization": "Bearer secret",
        },
    )

    observation = json.loads(tool_result_content(result))

    assert observation == {
        "artifact_uri": "artifact://report-1",
        "result_count": 3,
        "status": "executed",
    }


def test_failed_nonempty_result_keeps_status_and_reason() -> None:
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.FAILED,
        output="query returned no rows",
        metadata={"reason": "upstream_timeout"},
    )

    observation = json.loads(tool_result_content(result))

    assert observation == {
        "output": "query returned no rows",
        "reason": "upstream_timeout",
        "status": "failed",
    }


def test_plain_success_output_remains_provider_compatible() -> None:
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="plain output",
    )

    assert tool_result_content(result) == "plain output"


def test_blank_only_success_output_remains_a_valid_observation() -> None:
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="\n",
    )

    assert json.loads(tool_result_content(result)) == {"status": "executed"}


def test_failed_command_exposes_bounded_diagnostic_metadata_to_the_model() -> None:
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.FAILED,
        output="",
        metadata={
            "exit_code": 1,
            "failure_reason": "command_failed",
            "stderr": "AssertionError: expected one write",
            "timed_out": False,
        },
    )

    assert json.loads(tool_result_content(result)) == {
        "exit_code": 1,
        "failure_reason": "command_failed",
        "status": "failed",
        "stderr": "AssertionError: expected one write",
        "timed_out": False,
    }
