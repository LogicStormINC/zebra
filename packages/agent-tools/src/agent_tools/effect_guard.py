from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol, cast

from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.skills import SkillComponentIdentity
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
    effective_skill_component_identities: tuple[SkillComponentIdentity, ...]
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
        # Declarative metadata emission: it performs no external side effect
        # (validation failure is a pure local reject), so it must never be
        # recorded as an uncertain effect that would block later task rounds.
        "artifact.output_contract.emit",
    }
)

# Failures that are provably local with no external side effect (argument
# validation, registry rejection, declarative metadata validation). These
# settle as failed_no_effect so later rounds of the same stable Task are not
# blocked; only failures that could have had an external effect stay uncertain.
DETERMINISTIC_FAILURE_REASONS = frozenset(
    {
        "tool_validation_error",
        "invalid_output_contract",
        # Local loop-guard / read-dedup rejections: the call was NOT executed
        # (executed=false), so no external effect could have occurred.
        "repeated_tool_call",
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
    def effective_skill_component_identities(self) -> tuple[SkillComponentIdentity, ...]:
        return self._gateway.effective_skill_component_identities

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
            metadata = (
                result.metadata if isinstance(result.metadata, Mapping) else {}
            )
            if (
                tool_call.name.startswith("mcp.")
                or metadata.get("reason") in DETERMINISTIC_FAILURE_REASONS
            ):
                # Provably local failure: no external effect could have
                # occurred, so the effect settles cleanly and later rounds of
                # the same stable Task are not blocked. MCP transport calls
                # either complete or fail without a partially applied
                # external effect (product decision 2026-08-07), so their
                # failures settle the same way.
                self._ledger.mark_failed_no_effect(reservation)
            else:
                # A generic tool failure cannot prove that no external effect
                # occurred; keep it uncertain to protect later rounds.
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
