"""Client tool gateway acceptance (schedule-only semantics)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    canonical_client_capability_digest,
)
from agent_core.domain.client_run_bindings import ClientRunBinding
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
from zebra_agent_worker.tool_gateway_runtime import WorkerToolGateway

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
            fence_hash="d" * 64,
            session_id=new_session_id(),
            ui_revision=4,
            action_contracts={
                "app.ui.item.open": ClientActionContract(
                    name="app.ui.item.open",
                    description="Open one item",
                    parameters={
                        "type": "object",
                        "properties": {"itemId": {"type": "string"}},
                        "required": ["itemId"],
                        "additionalProperties": False,
                    },
                    risk=ClientActionRisk.PRESENTATION,
                )
            },
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
    contract = gateway.context.action_contracts["app.ui.item.open"]
    assert request.action_contract_digest == canonical_client_capability_digest(
        contract.model_dump(mode="json")
    )
    assert request.fence_hash == "d" * 64
    assert request.parent_session_id == gateway.context.session_id


def test_actions_outside_the_binding_fail_closed() -> None:
    from agent_core.domain.client_run_bindings import ClientBindingNarrowingError

    gateway, dispatch = _gateway()
    with pytest.raises(ClientBindingNarrowingError):
        gateway.execute(_call("app.ui.absent.open"))
    assert dispatch.scheduled == []


def test_model_tools_mirror_the_allowed_actions() -> None:
    gateway, _ = _gateway()
    assert [tool.name for tool in gateway.model_tools] == ["app.ui.item.open"]
    assert gateway.model_tools[0].parameters["required"] == ["itemId"]
    assert gateway.parallel_safe_tools == frozenset()
    assert gateway.authorized_policy_tools == frozenset({"app.ui.item.open"})
    assert gateway.approval_required_tools == frozenset()
    worker_gateway = WorkerToolGateway(local=object(), client=gateway)  # type: ignore[arg-type]
    assert worker_gateway.authorized_write_tools == frozenset({"app.ui.item.open"})
    assert worker_gateway.approval_required_tools == frozenset()


def test_user_interaction_action_requires_policy_approval() -> None:
    _, dispatch = _gateway()
    interaction = ClientActionContract(
        name="app.ui.confirm.open",
        description="Open a confirmation prompt",
        parameters={"type": "object", "additionalProperties": False},
        risk=ClientActionRisk.USER_INTERACTION,
    )
    gateway = ClientToolGateway(
        context=ClientGatewayContext(
            binding=_binding((interaction.name,)),
            fence_hash="d" * 64,
            session_id=new_session_id(),
            ui_revision=4,
            action_contracts={interaction.name: interaction},
        ),
        dispatch=dispatch,
    )

    assert gateway.authorized_policy_tools == frozenset()
    assert gateway.approval_required_tools == frozenset({interaction.name})
    worker_gateway = WorkerToolGateway(local=object(), client=gateway)  # type: ignore[arg-type]
    assert worker_gateway.authorized_write_tools == frozenset()
    assert worker_gateway.approval_required_tools == frozenset({interaction.name})
