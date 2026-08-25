"""Worker client tool gateway: the third execution channel.

Client tools never execute in the worker. Calling one only SCHEDULES a
durable client effect pinned to the binding, the control fence and the
expected UI revision; the harness then suspends as
``waiting_external_tool`` until the browser receipt resumes it
(ADR-CLIENT-01).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_control_plane.client_effects import (
    build_client_effect_continuation,
    build_client_effect_request,
)
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import ClientControlFence
from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.client_effect_dispatch import ClientEffectDispatchPort


class ClientToolGatewayError(ValueError):
    pass


@dataclass(frozen=True)
class ClientGatewayContext:
    """Everything the schedule-only channel needs for one run."""

    binding: ClientRunBinding
    fence: ClientControlFence
    session_id: SessionId
    ui_revision: int
    action_contract_digests: dict[str, str]


class ClientToolGateway:
    """Schedule-only gateway exposed beside local and host tools."""

    def __init__(
        self,
        *,
        context: ClientGatewayContext,
        dispatch: ClientEffectDispatchPort,
    ) -> None:
        self._context = context
        self._dispatch = dispatch

    @property
    def context(self) -> ClientGatewayContext:
        return self._context

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        return tuple(
            ModelToolDefinition(
                name=action,
                description=f"Client action {action} executed by the browser",
                parameters={"type": "object", "properties": {}},
            )
            for action in self._context.binding.allowed_actions
        )

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        return frozenset(self._context.binding.allowed_actions)

    def execute(self, tool_call: ToolCall) -> ToolResult:
        binding = self._context.binding
        binding.ensure_allows(tool_call.name)
        request = build_client_effect_request(
            binding=binding,
            tool_call_id=tool_call.tool_call_id,
            action_name=tool_call.name,
            arguments=dict(tool_call.arguments),
            action_contract_digest=self._context.action_contract_digests.get(
                tool_call.name, "0" * 64
            ),
            fence=self._context.fence,
            expected_ui_revision=self._context.ui_revision,
            session_id=self._context.session_id,
        )
        continuation = build_client_effect_continuation(
            request,
            assistant_message="",
            model_calls_used=0,
            tool_calls_executed=0,
        )
        outcome = self._dispatch.schedule(
            request, continuation=continuation, session_id=self._context.session_id
        )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="",
            metadata={
                "client_effect_deferred": True,
                "client_effect_id": str(outcome.effect.effect_id),
                "action_name": tool_call.name,
                "client_effect_idempotency_key": request.idempotency_key,
                "client_effect_scheduled": outcome.created,
            },
        )


def compose_client_tool_gateway(
    *,
    platform: Any,
    binding: ClientRunBinding,
    fence: ClientControlFence,
    session_id: SessionId,
    ui_revision: int,
    action_contract_digests: dict[str, str] | None = None,
) -> ClientToolGateway | None:
    """Expose client actions only when the platform stores are composed."""

    dispatch = getattr(platform, "client_effects", None)
    if dispatch is None:
        return None
    return ClientToolGateway(
        context=ClientGatewayContext(
            binding=binding,
            fence=fence,
            session_id=session_id,
            ui_revision=ui_revision,
            action_contract_digests=dict(action_contract_digests or {}),
        ),
        dispatch=dispatch,
    )
