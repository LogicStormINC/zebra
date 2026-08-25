"""Client tool gateway acceptance (schedule-only semantics)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import ClientControlFence
from agent_core.domain.identifiers import (
    new_client_run_binding_id,
    new_client_session_id,
    new_session_id,
    new_task_id,
    new_tool_call_id,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports.client_effect_dispatch import ClientEffectScheduleOutcome
from zebra_agent_worker.client_tool_gateway import (
    ClientGatewayContext,
    ClientToolGateway,
)

NOW = datetime.now(UTC)


class RecordingDispatch:
    def __init__(self) -> None:
        self.scheduled: list[object] = []

    def schedule(self, request, *, continuation, session_id):
        self.scheduled.append(request)
        return ClientEffectScheduleOutcome(effect=request, created=True)

    def get_effect(self, effect_id):
        return None

    def list_pending(self, client_session_id, *, limit=50):
        return ()

    def mark_delivered(self, effect_id) -> None:
        return None


def _binding(actions: tuple[str, ...]) -> ClientRunBinding:
    return ClientRunBinding(
        binding_id=new_client_run_binding_id(),
        task_id=new_task_id(),
        run_id="run-1",
        client_session_id=new_client_session_id(),
        profile_digest="a" * 64,
        mounted_snapshot_digest="b" * 64,
        task_capability_scope=tuple(actions),
        allowed_actions=actions,
        binding_revision=1,
        created_at=NOW,
    )


def _gateway(
    actions: tuple[str, ...] = ("app.ui.item.open",),
) -> tuple[ClientToolGateway, RecordingDispatch]:
    dispatch = RecordingDispatch()
    gateway = ClientToolGateway(
        context=ClientGatewayContext(
            binding=_binding(actions),
            fence=ClientControlFence.issue(),
            session_id=new_session_id(),
            ui_revision=4,
            action_contract_digests={"app.ui.item.open": "c" * 64},
        ),
        dispatch=dispatch,
    )
    return gateway, dispatch


def _call(name: str = "app.ui.item.open") -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments={"itemId": "item-1"},
        created_at=NOW,
    )


def test_execute_only_schedules_a_durable_effect() -> None:
    gateway, dispatch = _gateway()
    result = gateway.execute(_call())
    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata["client_effect_deferred"] is True
    assert result.metadata["client_effect_scheduled"] is True
    assert len(dispatch.scheduled) == 1
    request = dispatch.scheduled[0]
    assert request.expected_ui_revision == 4
    assert request.action_contract_digest == "c" * 64
    assert len(request.fence_hash) == 64


def test_actions_outside_the_binding_fail_closed() -> None:
    from agent_core.domain.client_run_bindings import ClientBindingNarrowingError

    gateway, dispatch = _gateway()
    with pytest.raises(ClientBindingNarrowingError):
        gateway.execute(_call("app.ui.absent.open"))
    assert dispatch.scheduled == []


def test_model_tools_mirror_the_allowed_actions() -> None:
    gateway, _ = _gateway()
    assert [tool.name for tool in gateway.model_tools] == ["app.ui.item.open"]
    assert gateway.parallel_safe_tools == frozenset({"app.ui.item.open"})
