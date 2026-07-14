from datetime import UTC, datetime

import pytest
from agent_core.domain import ArtifactAccessDescriptor
from agent_core.domain.artifacts import ArtifactRef
from agent_core.domain.identifiers import (
    new_artifact_id,
    new_message_id,
    new_tool_call_id,
)
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from pydantic import ValidationError


def test_session_message_can_be_instantiated() -> None:
    message = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content="  fix the failing test  ",
        created_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
    )

    assert message.content == "fix the failing test"
    assert message.role is MessageRole.USER


def test_session_message_rejects_blank_content() -> None:
    with pytest.raises(ValidationError, match="content must not be blank"):
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="   ",
            created_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
        )


def test_tool_message_requires_tool_call_id() -> None:
    with pytest.raises(ValidationError, match="tool messages require tool_call_id"):
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.TOOL,
            content="tool output",
            created_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
        )


def test_tool_models_can_be_instantiated() -> None:
    tool_call_id = new_tool_call_id()
    tool_call = ToolCall(
        tool_call_id=tool_call_id,
        name=" command.run ",
        arguments={"command": ["pytest"]},
        created_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
    )
    result = ToolResult(
        tool_call_id=tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="ok",
    )

    assert tool_call.name == "command.run"
    assert result.status is ToolCallStatus.EXECUTED


def test_model_tool_definition_rejects_non_object_parameter_schema() -> None:
    with pytest.raises(ValueError, match="object JSON schema"):
        ModelToolDefinition(
            name="files.read",
            description="Read a file.",
            parameters={"type": "string", "properties": {}},
        )


def test_artifact_and_policy_models_can_be_instantiated() -> None:
    artifact = ArtifactRef(
        artifact_id=new_artifact_id(),
        kind=" test-report ",
        uri=" file:///tmp/report.txt ",
        created_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
    )
    decision = PolicyDecision(
        decision=PolicyDecisionType.REQUIRE_APPROVAL,
        reason="writes outside workspace root",
        policy_profile="workspace_write",
    )

    assert artifact.kind == "test-report"
    assert artifact.uri == "file:///tmp/report.txt"
    assert decision.decision is PolicyDecisionType.REQUIRE_APPROVAL


def test_artifact_access_descriptor_normalizes_optional_strings() -> None:
    descriptor = ArtifactAccessDescriptor(
        kind=" tool_output ",
        mime_type=" text/plain ",
        uri=" file:///tmp/report.txt ",
    )

    assert descriptor.kind == "tool_output"
    assert descriptor.mime_type == "text/plain"
    assert descriptor.uri == "file:///tmp/report.txt"


def test_tool_call_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="command.run",
            arguments={},
            created_at=datetime(2026, 6, 18, 10, 0),
        )
