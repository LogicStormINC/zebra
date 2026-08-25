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
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    canonical_client_capability_digest,
)
from agent_core.domain.client_run_bindings import ClientRunBinding
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
    fence_hash: str
    session_id: SessionId
    ui_revision: int
    action_contracts: dict[str, ClientActionContract]


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
        tools: list[ModelToolDefinition] = []
        for name in self._context.binding.allowed_actions:
            contract = self._context.action_contracts.get(name)
            if contract is None:
                raise ClientToolGatewayError(f"published action contract missing for {name}")
            tools.append(
                ModelToolDefinition(
                    name=name,
                    description=contract.description,
                    parameters=contract.parameters,
                )
            )
        return tuple(tools)

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        return frozenset()

    def execute(self, tool_call: ToolCall) -> ToolResult:
        binding = self._context.binding
        binding.ensure_allows(tool_call.name)
        contract = self._context.action_contracts.get(tool_call.name)
        if contract is None:
            raise ClientToolGatewayError(f"published action contract missing for {tool_call.name}")
        request = build_client_effect_request(
            binding=binding,
            tool_call_id=tool_call.tool_call_id,
            action_name=tool_call.name,
            arguments=dict(tool_call.arguments),
            action_contract_digest=canonical_client_capability_digest(
                contract.model_dump(mode="json")
            ),
            fence_hash=self._context.fence_hash,
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
    fence_hash: str,
    session_id: SessionId,
    ui_revision: int,
    action_contracts: dict[str, ClientActionContract] | None = None,
) -> ClientToolGateway | None:
    """Expose client actions only when the platform stores are composed."""

    dispatch = getattr(platform, "client_effects", None)
    if dispatch is None:
        return None
    return ClientToolGateway(
        context=ClientGatewayContext(
            binding=binding,
            fence_hash=fence_hash,
            session_id=session_id,
            ui_revision=ui_revision,
            action_contracts=dict(action_contracts or {}),
        ),
        dispatch=dispatch,
    )
