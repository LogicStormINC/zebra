from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.effect_dispatch import (
    EffectDispatch,
    EffectDispatchStateError,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import ArtifactPayloadStorePort, EffectDispatchPort


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
            # A generic tool failure cannot prove that no external effect occurred.
            self._ledger.mark_uncertain(reservation)
        return result


class FencedEffectToolGateway:
    """Runs effectful tools through the durable fenced dispatch queue."""

    def __init__(
        self,
        gateway: ToolGatewayLike,
        *,
        dispatch: EffectDispatchPort,
        artifacts: ArtifactPayloadStorePort,
        execution_session_id: SessionId,
        root_session_id: SessionId,
        fence: LeaseFence,
        claim_ttl: timedelta,
        authority_scope: str,
        next_event: Callable[[EventType, EventActor, dict[str, object]], SessionEvent],
        accept_event: Callable[[SessionEvent], object],
        ownership_check: Callable[[], None],
    ) -> None:
        if claim_ttl <= timedelta(0):
            raise ValueError("effect claim ttl must be positive")
        self._gateway = gateway
        self._dispatch = dispatch
        self._artifacts = artifacts
        self._execution_session_id = execution_session_id
        self._root_session_id = root_session_id
        self._fence = fence
        self._claim_ttl = claim_ttl
        self._authority_scope = authority_scope
        self._next_event = next_event
        self._accept_event = accept_event
        self._ownership_check = ownership_check

    def __getattr__(self, name: str) -> object:
        return getattr(self._gateway, name)

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
        return self._gateway.parallel_safe_tools & READ_ONLY_TOOLS

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return self._gateway.parallel_batch_limits

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        return self._gateway.resolve_model_tool_calls(tool_calls)

    def close(self) -> None:
        self._gateway.close()

    def manages_durable_effect(self, tool_call: ToolCall) -> bool:
        return tool_call.name not in READ_ONLY_TOOLS

    def reconcile_expired(self, *, limit: int = 100) -> int:
        self._ownership_check()
        claims = self._dispatch.list_reconcilable(
            self._execution_session_id,
            current_fence=self._fence,
            limit=limit,
        )
        for claim in claims:
            self._dispatch.reconcile_expired(
                claim.dispatch.dispatch_id,
                old_claim=claim,
                current_fence=self._fence,
                evidence=EffectEvidence(reason_code="worker_recovery_claim_expired"),
            )
        return len(claims)

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self._ownership_check()
        if tool_call.name in READ_ONLY_TOOLS:
            return self._gateway.execute(tool_call)
        scheduled = self._schedule(tool_call)
        if scheduled.result is not None:
            return scheduled.result
        while True:
            self._ownership_check()
            claim = self._dispatch.claim_next(
                self._execution_session_id,
                fence=self._fence,
                claim_ttl=self._claim_ttl,
            )
            if claim is None:
                raise EffectDispatchStateError("scheduled Effect was not claimable")
            claimed_call = self._read_tool_call(claim.dispatch.payload_artifact_ref)
            try:
                result = self._gateway.execute(claimed_call)
            except BaseException as error:
                try:
                    terminal = self._terminal_event(claimed_call, None)
                    persisted = self._dispatch.mark_uncertain(
                        claim,
                        evidence=EffectEvidence(reason_code="provider_call_raised"),
                        terminal_event=terminal,
                    )
                    self._accept_event(persisted)
                except Exception as terminal_error:
                    error.add_note(f"Effect uncertain commit failed: {terminal_error}")
                raise
            terminal = self._terminal_event(claimed_call, result)
            if result.status is ToolCallStatus.EXECUTED:
                persisted = self._dispatch.complete(
                    claim,
                    result=result,
                    terminal_event=terminal,
                )
            else:
                persisted = self._dispatch.mark_uncertain(
                    claim,
                    evidence=_uncertain_evidence(result),
                    terminal_event=terminal,
                )
            self._accept_event(persisted)
            if claim.dispatch.dispatch_id == scheduled.dispatch_id:
                return result

    def _schedule(self, tool_call: ToolCall) -> EffectDispatch:
        encoded = tool_call.model_dump_json().encode()
        artifact = self._artifacts.store_payload(
            ArtifactPayloadWrite(
                session_id=self._execution_session_id,
                kind="effect_tool_call",
                mime_type="application/json",
                payload=encoded,
                file_name="tool-call.json",
                created_at=datetime.now(UTC),
            )
        )
        started = self._next_event(
            EventType.TOOL_EXECUTION_STARTED,
            EventActor.HARNESS,
            _event_payload(tool_call),
        )
        identity = effect_identity(tool_call, self._authority_scope)
        scheduled = self._dispatch.schedule(
            EffectScheduleRequest(
                root_session_id=self._root_session_id,
                identity=identity,
                request_hash=identity.canonical_effect_hash,
                payload_artifact_ref=artifact.uri,
                started_event=started,
            ),
            fence=self._fence,
        )
        if scheduled.intent_event_id == started.event_id:
            self._accept_event(started)
        return scheduled

    def _read_tool_call(self, artifact_ref: str) -> ToolCall:
        prefix = "artifact://"
        if not artifact_ref.startswith(prefix):
            raise EffectDispatchStateError("Effect payload is not a governed artifact")
        try:
            artifact_id = ArtifactId(UUID(artifact_ref.removeprefix(prefix)))
        except ValueError as error:
            raise EffectDispatchStateError("Effect payload artifact id is invalid") from error
        return ToolCall.model_validate_json(self._artifacts.read_payload_bytes(artifact_id))

    def _terminal_event(
        self,
        tool_call: ToolCall,
        result: ToolResult | None,
    ) -> SessionEvent:
        payload = _event_payload(tool_call)
        payload.update(
            {
                "status": ToolCallStatus.FAILED.value if result is None else result.status.value,
                "output": "" if result is None else result.output,
                "metadata": {"effect_status": "uncertain"}
                if result is None
                else result.metadata,
            }
        )
        return self._next_event(
            EventType.TOOL_EXECUTION_COMPLETED
            if result is not None and result.status is ToolCallStatus.EXECUTED
            else EventType.TOOL_EXECUTION_FAILED,
            EventActor.TOOL,
            payload,
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


def _event_payload(tool_call: ToolCall) -> dict[str, object]:
    return {
        "attempt_number": 1,
        "tool_name": tool_call.name,
        "tool_call_id": str(tool_call.tool_call_id),
    }


def _uncertain_evidence(result: ToolResult) -> EffectEvidence:
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
