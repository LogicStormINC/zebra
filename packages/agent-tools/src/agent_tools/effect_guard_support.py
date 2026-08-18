"""Shared contracts and deterministic identity helpers for Effect gateways."""

import hashlib
import json
from typing import Any, Protocol

from agent_core.domain.effect_dispatch import EffectClaim, EffectDispatch, EffectEvidence
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.ports import WorkerMutationAuthority


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
    parallel_batch_limits: dict[str, int]

    def execute(self, tool_call: ToolCall) -> ToolResult: ...

    def resolve_model_tool_calls(
        self, tool_calls: tuple[ToolCall, ...]
    ) -> tuple[ToolCall, ...]: ...

    def close(self) -> None: ...


def read_only_tool_names(gateway: ToolGatewayLike) -> frozenset[str]:
    """Combine the static local set with manifest-declared read tools."""

    declared = getattr(gateway, "read_only_tools", ())
    if isinstance(declared, frozenset | set | tuple):
        return READ_ONLY_TOOLS | frozenset(name for name in declared if isinstance(name, str))
    return READ_ONLY_TOOLS


class EffectPayloadCoordinatorLike(Protocol):
    def request_artifact_ref(
        self,
        *,
        root_session_id: SessionId,
        identity: EffectIdentity,
    ) -> str: ...

    def prepare_schedule(
        self,
        tool_call: ToolCall,
        *,
        root_session_id: SessionId,
        identity: EffectIdentity,
        started_event: SessionEvent,
        authority: WorkerMutationAuthority,
    ) -> EffectDispatch: ...

    def read_tool_call(self, artifact_ref: str, *, namespace: str) -> ToolCall: ...

    def complete_with_payload(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
    ) -> SessionEvent | None: ...

    def mark_uncertain_with_payload(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
    ) -> SessionEvent | None: ...


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


def effect_event_payload(tool_call: ToolCall) -> dict[str, object]:
    return {
        "attempt_number": 1,
        "tool_name": tool_call.name,
        "tool_call_id": str(tool_call.tool_call_id),
    }


def uncertain_evidence(result: ToolResult) -> EffectEvidence:
    operation_id = result.metadata.get("provider_operation_id")
    operation_hash = (
        hashlib.sha256(operation_id.encode()).hexdigest()
        if isinstance(operation_id, str) and operation_id
        else None
    )
    return EffectEvidence(
        reason_code="provider_result_did_not_prove_no_effect",
        provider_operation_id_hash=operation_hash,
    )
