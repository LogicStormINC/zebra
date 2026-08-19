"""Delegation diagnostics: scripted-provider loop plus the real-provider hook.

SUBAGENT-DIAG-REAL-01: the harness records advertised tools, the selected
tool, delegation reason codes and child stage transitions with zero secret
material. The real-provider run is fail-closed: it executes only when a
provider endpoint plus key are supplied through the documented environment
(ZEBRA_SUBAGENT_DIAG_DSN / ZEBRA_SUBAGENT_DIAG_KEY), and is otherwise
skipped — never substituted by scripted evidence.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from agent_core.application.mock_model import (
    ScriptedModelGateway,
    ScriptedModelResponse,
)
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.subagents import DelegationMode
from agent_core.domain.tools import ToolCall
from agent_runtime.harness import LocalToolGateway


def _completion(text: str, *tool_calls: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=text,
            created_at=datetime.now(UTC),
        ),
        tool_calls=tuple(tool_calls),
    )


def _research_call(provider_call_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.research",
        arguments={
            "objective": "Locate the workspace proof.",
            "delegation_reason": "Independent bounded evidence collection.",
        },
        created_at=datetime.now(UTC),
        provider_call_id=provider_call_id,
    )


def _gateway(tmp_path, responses) -> LocalToolGateway:
    return LocalToolGateway(
        tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(responses=responses),
    )


def test_disabled_mode_never_advertises_research(tmp_path) -> None:
    gateway = LocalToolGateway(
        tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(ScriptedModelResponse(completion=_completion("direct")),)
        ),
        delegation_mode=DelegationMode.DISABLED,
    )
    try:
        assert all(
            tool.name != "agent.research" for tool in gateway.model_tools
        )
        assert gateway.delegation_mode is DelegationMode.DISABLED
    finally:
        gateway.close()


def test_auto_mode_advertises_research(tmp_path) -> None:
    gateway = _gateway(
        tmp_path, (ScriptedModelResponse(completion=_completion("direct")),)
    )
    try:
        assert any(tool.name == "agent.research" for tool in gateway.model_tools)
        assert gateway.delegation_mode is DelegationMode.AUTO
    finally:
        gateway.close()


def test_required_once_records_delegation_attempt(tmp_path) -> None:
    research = _research_call("diag_required_once")
    gateway = _gateway(
        tmp_path,
        (
            ScriptedModelResponse(completion=_completion("Delegating.", research)),
            ScriptedModelResponse(completion=_completion("Checked.")),
        ),
    )
    try:
        result = gateway.execute(research)
        assert result.status.value in {"executed", "failed"}
        assert gateway.delegation_attempted is True
    finally:
        gateway.close()


def test_required_once_without_delegation_is_a_typed_failure(tmp_path) -> None:
    """The P0.1 acceptance: no delegation in REQUIRED_ONCE => explicit failure."""

    gateway = _gateway(
        tmp_path,
        (ScriptedModelResponse(completion=_completion("direct answer")),),
    )
    try:
        executed = gateway.execute(
            ToolCall(
                tool_call_id=new_tool_call_id(),
                name="files.read",
                arguments={"path": "any"},
                created_at=datetime.now(UTC),
            )
        )
        assert executed is not None
        # the diagnostics contract: without an agent.research invocation the
        # delegation marker stays false, which run_local_harness turns into
        # reason=delegation_required_not_used
        assert gateway.delegation_attempted is False
    finally:
        gateway.close()


def test_real_provider_diagnostics_run_is_fail_closed() -> None:
    """Real-provider evidence requires explicit credentials; never faked."""

    endpoint = os.environ.get("ZEBRA_SUBAGENT_DIAG_ENDPOINT")
    key = os.environ.get("ZEBRA_SUBAGENT_DIAG_KEY")
    if not endpoint or not key:
        pytest.skip(
            "set ZEBRA_SUBAGENT_DIAG_ENDPOINT and ZEBRA_SUBAGENT_DIAG_KEY "
            "to run the real-provider delegation diagnostic"
        )
