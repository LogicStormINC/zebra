from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStateError,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import (
    ArtifactPayloadStorePort,
    EffectDispatchPort,
    WorkerMutationAuthority,
)

from agent_tools.effect_guard_support import (
    EffectPayloadCoordinatorLike,
    ToolGatewayLike,
    effect_event_payload,
    effect_identity,
    read_only_tool_names,
    uncertain_evidence,
)
from agent_tools.legacy_effect_guard import EffectGuardedToolGateway as EffectGuardedToolGateway


class FencedEffectToolGateway:
    """Runs effectful tools through the durable fenced dispatch queue."""

    def __init__(
        self,
        gateway: ToolGatewayLike,
        *,
        dispatch: EffectDispatchPort,
        artifacts: ArtifactPayloadStorePort | None,
        execution_session_id: SessionId,
        root_session_id: SessionId,
        fence: LeaseFence,
        claim_ttl: timedelta,
        authority_scope: str,
        next_event: Callable[[EventType, EventActor, dict[str, object]], SessionEvent],
        accept_event: Callable[[SessionEvent], object],
        ownership_check: Callable[[], None],
        effect_payloads: EffectPayloadCoordinatorLike | None = None,
        mutation_authority: Callable[[], WorkerMutationAuthority] | None = None,
    ) -> None:
        if claim_ttl <= timedelta(0):
            raise ValueError("effect claim ttl must be positive")
        if artifacts is None and effect_payloads is None:
            raise ValueError("Effect dispatch requires one payload strategy")
        if (effect_payloads is None) != (mutation_authority is None):
            raise ValueError("cloud Effect payload coordination requires Worker authority")
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
        self._effect_payloads = effect_payloads
        self._mutation_authority = mutation_authority

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
        return self._gateway.parallel_safe_tools & read_only_tool_names(self._gateway)

    @property
    def read_only_tools(self) -> frozenset[str]:
        return read_only_tool_names(self._gateway)

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return self._gateway.parallel_batch_limits

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        return self._gateway.resolve_model_tool_calls(tool_calls)

    def close(self) -> None:
        self._gateway.close()

    def manages_durable_effect(self, tool_call: ToolCall) -> bool:
        return tool_call.name not in read_only_tool_names(self._gateway)

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
        if tool_call.name in read_only_tool_names(self._gateway):
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
                persisted = self._complete(claim, result, terminal)
            else:
                persisted = self._mark_uncertain(claim, result, terminal)
            self._accept_event(persisted)
            if claim.dispatch.dispatch_id == scheduled.dispatch_id:
                return result

    def _schedule(self, tool_call: ToolCall) -> EffectDispatch:
        identity = effect_identity(tool_call, self._authority_scope)
        find_existing = getattr(self._dispatch, "find_by_ledger_key", None)
        if callable(find_existing):
            existing = find_existing(self._root_session_id, identity=identity)
            if existing is not None:
                if (
                    existing.identity != identity
                    or existing.request_hash != identity.canonical_effect_hash
                ):
                    raise EffectDispatchConflictError(
                        "effect ledger identity has conflicting meaning"
                    )
                # Business-identical replay: the stored payload is
                # authoritative — never mint a competing artifact for it.
                return existing
        if self._effect_payloads is not None:
            payload_ref = self._effect_payloads.request_artifact_ref(
                root_session_id=self._root_session_id,
                identity=identity,
            )
            payload = effect_event_payload(tool_call)
            payload["metadata"] = {"artifact_uri": payload_ref}
            started = self._next_event(
                EventType.TOOL_EXECUTION_STARTED,
                EventActor.HARNESS,
                payload,
            )
            scheduled = self._effect_payloads.prepare_schedule(
                tool_call,
                root_session_id=self._root_session_id,
                identity=identity,
                started_event=started,
                authority=self._require_mutation_authority(),
            )
        else:
            assert self._artifacts is not None
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
                effect_event_payload(tool_call),
            )
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
        if self._effect_payloads is not None:
            authority = self._require_mutation_authority()
            return self._effect_payloads.read_tool_call(
                artifact_ref,
                namespace=authority.deployment_namespace,
            )
        assert self._artifacts is not None
        prefix = "artifact://"
        if not artifact_ref.startswith(prefix):
            raise EffectDispatchStateError("Effect payload is not a governed artifact")
        try:
            artifact_id = ArtifactId(UUID(artifact_ref.removeprefix(prefix)))
        except ValueError as error:
            raise EffectDispatchStateError("Effect payload artifact id is invalid") from error
        return ToolCall.model_validate_json(self._artifacts.read_payload_bytes(artifact_id))

    def _complete(
        self,
        claim: EffectClaim,
        result: ToolResult,
        terminal_event: SessionEvent,
    ) -> SessionEvent:
        if self._effect_payloads is not None:
            persisted = self._effect_payloads.complete_with_payload(
                claim,
                result=result,
                terminal_event=terminal_event,
                authority=self._require_mutation_authority(),
            )
            if persisted is not None:
                return persisted
        return self._dispatch.complete(claim, result=result, terminal_event=terminal_event)

    def _mark_uncertain(
        self,
        claim: EffectClaim,
        result: ToolResult,
        terminal_event: SessionEvent,
    ) -> SessionEvent:
        evidence = uncertain_evidence(result)
        if self._effect_payloads is not None:
            persisted = self._effect_payloads.mark_uncertain_with_payload(
                claim,
                result=result,
                evidence=evidence,
                terminal_event=terminal_event,
                authority=self._require_mutation_authority(),
            )
            if persisted is not None:
                return persisted
        return self._dispatch.mark_uncertain(
            claim,
            evidence=evidence,
            terminal_event=terminal_event,
        )

    def _require_mutation_authority(self) -> WorkerMutationAuthority:
        if self._mutation_authority is None:
            raise EffectDispatchStateError("cloud Effect payload authority is unavailable")
        return self._mutation_authority()

    def _terminal_event(
        self,
        tool_call: ToolCall,
        result: ToolResult | None,
    ) -> SessionEvent:
        payload = effect_event_payload(tool_call)
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
