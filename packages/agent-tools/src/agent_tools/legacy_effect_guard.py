"""Local compatibility Effect ledger gateway."""

from typing import cast

from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult

from agent_tools.effect_guard_support import (
    READ_ONLY_TOOLS,
    EffectLedgerLike,
    ToolGatewayLike,
    effect_identity,
)


class EffectGuardedToolGateway:
    def __init__(
        self,
        gateway: ToolGatewayLike,
        *,
        ledger: EffectLedgerLike,
        root_session_id: SessionId,
        authority_scope: str,
    ) -> None:
        self._gateway = gateway
        self._ledger = ledger
        self._root_session_id = root_session_id
        self._authority_scope = authority_scope

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self._gateway.model_tools

    @property
    def effective_mcp_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self._gateway.effective_mcp_tools

    @property
    def effective_skill_components(self) -> tuple[str, ...]:
        return self._gateway.effective_skill_components

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        return self._gateway.parallel_safe_tools

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return self._gateway.parallel_batch_limits

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        return self._gateway.resolve_model_tool_calls(tool_calls)

    def close(self) -> None:
        self._gateway.close()

    def execute(self, tool_call: ToolCall) -> ToolResult:
        if tool_call.name in READ_ONLY_TOOLS:
            return self._gateway.execute(tool_call)
        reservation = self._ledger.reserve(
            self._root_session_id, effect_identity(tool_call, self._authority_scope)
        )
        if reservation.replay:
            result = cast(ToolResult | None, reservation.result)
            assert result is not None
            return result
        self._ledger.mark_executing(reservation)
        try:
            result = self._gateway.execute(tool_call)
        except BaseException:
            self._ledger.mark_uncertain(reservation)
            raise
        if result.status is ToolCallStatus.EXECUTED:
            self._ledger.mark_succeeded(reservation, result)
        else:
            self._ledger.mark_uncertain(reservation)
        return result
