from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, cast

from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult


class EffectLedgerLike(Protocol):
    def reserve(
        self,
        root_session_id: SessionId,
        identity: EffectIdentity,
        *,
        explicit_retry: bool = False,
    ) -> Any: ...

    def mark_executing(self, reservation: Any) -> None: ...

    def mark_succeeded(self, reservation: Any, result: ToolResult) -> None: ...

    def mark_uncertain(self, reservation: Any) -> None: ...


class ToolGatewayLike(Protocol):
    model_tools: tuple[ModelToolDefinition, ...]
    effective_mcp_tools: tuple[ModelToolDefinition, ...]
    effective_skill_components: tuple[str, ...]
    parallel_safe_tools: frozenset[str]
    read_only_tools: frozenset[str]
    validator_tools: frozenset[str]
    parallel_batch_limits: dict[str, int]

    def execute(self, tool_call: ToolCall) -> ToolResult: ...

    def resolve_model_tool_calls(
        self, tool_calls: tuple[ToolCall, ...]
    ) -> tuple[ToolCall, ...]: ...

    def close(self) -> None: ...


READ_ONLY_TOOLS = frozenset(
    {
        "files.read",
        "files.search",
        "files.list",
        "git.status",
        "sessions.search",
        "skills.list",
        "skills.read",
        "web.fetch",
        "web.search",
        "agent.research",
        "agent.plan",
        "agent.clarify",
    }
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
    def validator_tools(self) -> frozenset[str]:
        return self._gateway.validator_tools

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return self._gateway.parallel_batch_limits

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        return self._gateway.resolve_model_tool_calls(tool_calls)

    def close(self) -> None:
        self._gateway.close()

    def execute(self, tool_call: ToolCall) -> ToolResult:
        if (
            tool_call.name in READ_ONLY_TOOLS
            or tool_call.name in self._gateway.read_only_tools
            or tool_call.name in self._gateway.validator_tools
        ):
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
            # A generic tool failure cannot prove that no external effect occurred.
            self._ledger.mark_uncertain(reservation)
        return result


def effect_identity(tool_call: ToolCall, authority_scope: str) -> EffectIdentity:
    arguments = json.dumps(
        tool_call.arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(arguments.encode()).hexdigest()
    return EffectIdentity(
        authority_scope_hash=hashlib.sha256(authority_scope.encode()).hexdigest(),
        tool_name=tool_call.name,
        operation_kind=tool_call.name,
        target_hash=digest,
        canonical_effect_hash=hashlib.sha256(f"{tool_call.name}\0{arguments}".encode()).hexdigest(),
    )
