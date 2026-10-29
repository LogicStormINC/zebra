from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchConflictError,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectResolutionOutcome,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_effect_receipts import HostEffectReceipt, HostEffectStatus
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import (
    ArtifactPayloadStorePort,
    EffectDispatchPort,
    WorkerMutationAuthority,
)
from agent_core.ports.effect_dispatch import effect_input

from agent_tools.effect_guard_support import (
    EffectPayloadCoordinatorLike,
    ToolGatewayLike,
    effect_event_payload,
    effect_identity,
    proves_failed_no_effect,
    read_only_tool_names,
    uncertain_evidence,
)
from agent_tools.effect_payload_admission import settle_unreadable_payload
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
        mutation_guard: Callable[[], AbstractContextManager[object]] = nullcontext,
        execution_started: Callable[[str], None] | None = None,
        payloadless_readonly: bool = False,
    ) -> None:
        if claim_ttl <= timedelta(0):
            raise ValueError("effect claim ttl must be positive")
        shown = frozenset(tool.name for tool in gateway.model_tools) if payloadless_readonly else frozenset()
        if payloadless_readonly and (not shown or not shown <= read_only_tool_names(gateway)
                or artifacts is not None or effect_payloads is not None):
            raise ValueError("payloadless execution requires an exclusively readonly tool surface")
        self._payloadless_readonly_tools = shown if payloadless_readonly else None
        if artifacts is None and effect_payloads is None and not payloadless_readonly:
            raise ValueError("Effect dispatch requires one payload strategy")
        if (effect_payloads is None) != (mutation_authority is None):
            raise ValueError("cloud Effect payload coordination requires Worker authority")
        self._gateway = gateway
        self._fresh_authority_check = getattr(gateway, "fresh_authority_check", None)
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
        self._mutation_guard = mutation_guard
        self._execution_started = execution_started
        self.execution_finished_listener: Callable[[ToolCall, ToolResult | None], None] | None = (
            None)

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

    def reconcile_uncertain(self, *, limit: int = 100) -> int:
        self._ownership_check()
        list_uncertain = getattr(self._dispatch, "list_uncertain", None)
        resolver = getattr(self._gateway, "reconcile_effect_receipt", None)
        if not callable(list_uncertain) or not callable(resolver):
            return 0
        dispatches: tuple[EffectDispatch, ...] = list_uncertain(
            self._execution_session_id,
            current_fence=self._fence,
            limit=limit,
        )
        resolved = 0
        for dispatch in dispatches:
            self._ownership_check()
            evidence = dispatch.evidence
            receipt = None if evidence is None else evidence.host_effect_receipt
            if receipt is None:
                continue
            settled: HostEffectReceipt = resolver(receipt)
            if not settled.reconciled:
                continue
            tool_call = self._read_tool_call(dispatch.payload_artifact_ref)
            result = ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=(
                    ToolCallStatus.EXECUTED
                    if settled.effect_status is HostEffectStatus.SUCCEEDED
                    else ToolCallStatus.FAILED
                ),
                output="Host Effect reconciled from its durable receipt.",
                metadata={
                    "provider_operation_id": settled.provider_operation_id,
                    "business_revision": settled.business_revision,
                    "business_outcome": (
                        "applied"
                        if settled.effect_status is HostEffectStatus.SUCCEEDED
                        else "rejected"
                    ),
                    "transport_outcome": "returned",
                    "host_effect_receipt": settled.model_dump(mode="json"),
                },
            )
            with self._mutation_guard():
                terminal = self._terminal_event(tool_call, result)
                persisted = self._dispatch.resolve_uncertain(
                    dispatch.dispatch_id,
                    current_fence=self._fence,
                    evidence=EffectEvidence(
                        reason_code="host_receipt_reconciled",
                        provider_operation_id_hash=sha256(
                            settled.provider_operation_id.encode()
                        ).hexdigest(),
                        host_effect_receipt=settled,
                    ),
                    outcome=(
                        EffectResolutionOutcome.SUCCEEDED
                        if settled.effect_status is HostEffectStatus.SUCCEEDED
                        else EffectResolutionOutcome.FAILED_NO_EFFECT
                    ),
                    terminal_event=terminal,
                    result=(
                        result if settled.effect_status is HostEffectStatus.SUCCEEDED else None
                    ),
                )
                self._accept_event(persisted)
            resolved += 1
        return resolved

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self._ownership_check()
        if self._fresh_authority_check is not None:
            self._fresh_authority_check("effect_admission", str(tool_call.tool_call_id))
        if self._payloadless_readonly_tools is not None and tool_call.name not in self._payloadless_readonly_tools:
            raise EffectDispatchStateError("tool is outside the frozen payloadless readonly surface")
        if tool_call.name in read_only_tool_names(self._gateway):
            return self._gateway.execute(tool_call)
        with self._mutation_guard():
            scheduled = self._schedule(tool_call)
        if scheduled.result is not None:
            return scheduled.result
        while True:
            self._ownership_check()
            claim = self._dispatch.claim_next(
                self._execution_session_id, fence=self._fence, claim_ttl=self._claim_ttl
            )
            if claim is None:
                raise EffectDispatchStateError("scheduled Effect was not claimable")
            claimed_call: ToolCall | None = None
            observed_result: ToolResult | None = None
            error: BaseException | None = None
            try:
                try:
                    claimed_call = self._read_tool_call(claim.dispatch.payload_artifact_ref)
                except BaseException as admission_error:
                    claimed_call = settle_unreadable_payload(
                        claim,
                        admission_error,
                        dispatch=self._dispatch,
                        ownership_check=self._ownership_check,
                        mutation_guard=self._mutation_guard,
                        next_event=self._next_event,
                        accept_event=self._accept_event,
                    )
                    raise
                result = self._execute_claim(claim, claimed_call)
                observed_result = result  # publish success only after fenced terminal acceptance
            except BaseException as execution_error:
                error = execution_error
                raise
            finally:
                if claimed_call is not None and self.execution_finished_listener is not None:
                    try:
                        self.execution_finished_listener(claimed_call, observed_result)
                    except BaseException as observer_error:
                        if error is None:
                            raise
                        error.add_note(f"Effect terminal observer failed: {observer_error}")
            if claim.dispatch.dispatch_id == scheduled.dispatch_id:
                return result

    def _execute_claim(self, claim: EffectClaim, claimed_call: ToolCall) -> ToolResult:
        dispatched = False
        try:
            # Payload retrieval and the observer can both outlive ownership.
            self._ownership_check()
            if self._fresh_authority_check is not None:
                self._fresh_authority_check("effect_dispatch", str(claimed_call.tool_call_id))
            if self._execution_started is not None:
                self._execution_started(str(claimed_call.tool_call_id))
            self._ownership_check()
            dispatched = True
            result = self._gateway.execute(claimed_call)
        except BaseException as error:
            try:
                with self._mutation_guard():
                    terminal = self._terminal_event(
                        claimed_call,
                        None
                        if dispatched
                        else ToolResult(
                            tool_call_id=claimed_call.tool_call_id,
                            status=ToolCallStatus.FAILED,
                            metadata={"effect_status": "failed_no_effect",
                                      "execution_state": "not_executed"},
                        ),
                    )
                    commit = (self._dispatch.mark_uncertain if dispatched
                              else self._dispatch.fail_no_effect)
                    persisted = commit(
                        claim,
                        evidence=EffectEvidence(reason_code=(
                            "provider_call_raised" if dispatched else "provider_call_not_dispatched"
                        )),
                        terminal_event=terminal,
                    )
                    self._accept_event(persisted)
            except BaseException as terminal_error:
                error.add_note(f"Effect terminal commit failed: {terminal_error}")
            raise
        # Keep the provider call OUTSIDE this short event mutation boundary.
        # Artifact staging is included because its intent binds an event sequence.
        with self._mutation_guard():
            terminal = self._terminal_event(claimed_call, result)
            if result.status is ToolCallStatus.EXECUTED:
                persisted = self._complete(claim, result, terminal)
            elif proves_failed_no_effect(result):
                persisted = self._fail_no_effect(claim, result, terminal)
            else:
                persisted = self._mark_uncertain(claim, result, terminal)
            self._accept_event(persisted)
        return result

    def execute_exact(self, tool_call: ToolCall) -> ToolResult:
        """Execute only this Effect; caller owns policy and fresh external authority."""
        self._ownership_check()
        if self._fresh_authority_check is not None:
            self._fresh_authority_check("effect_exact", str(tool_call.tool_call_id))
        if self._payloadless_readonly_tools is not None:
            raise EffectDispatchStateError("payloadless readonly execution has no exact Effects")
        tool_call = ToolCall.model_validate(effect_input(tool_call), strict=True, extra="forbid")
        LeaseFence.model_validate(effect_input(self._fence), strict=True, extra="forbid")
        if not self.manages_durable_effect(tool_call):
            raise EffectDispatchStateError("exact execution requires an effectful tool")
        with self._mutation_guard():
            scheduled = EffectDispatch.model_validate(
                effect_input(self._schedule(tool_call)), strict=True, extra="forbid"
            )
        identity = effect_identity(tool_call, self._authority_scope)
        if (
            scheduled.execution_session_id != self._execution_session_id
            or scheduled.root_session_id != self._root_session_id
            or scheduled.identity != identity
            or scheduled.request_hash != identity.canonical_effect_hash
        ):
            raise EffectDispatchConflictError("scheduled Effect identity conflicts")
        original = ToolCall.model_validate(
            effect_input(self._read_tool_call(scheduled.payload_artifact_ref)),
            strict=True, extra="forbid",
        )
        if (
            (original.tool_call_id, original.name, original.arguments)
            != (tool_call.tool_call_id, tool_call.name, tool_call.arguments)
            or effect_identity(original, self._authority_scope) != identity
        ):
            raise EffectDispatchConflictError("durable Effect request conflicts")
        self._ownership_check()
        if scheduled.status is EffectDispatchStatus.SUCCEEDED:
            if scheduled.result is None or scheduled.result.tool_call_id != tool_call.tool_call_id:
                raise EffectDispatchConflictError("durable Effect result identity conflicts")
            return scheduled.result
        if scheduled.status is not EffectDispatchStatus.PENDING:
            raise EffectDispatchStateError("exact Effect is not pending; no reissue permitted")
        claim = self._dispatch.claim_exact(
            self._execution_session_id, expected=scheduled,
            fence=self._fence, claim_ttl=self._claim_ttl,
        )
        if claim is None:
            raise EffectDispatchStateError("exact Effect was not claimable")
        return self._execute_claim(claim, original)

    def _schedule(self, tool_call: ToolCall) -> EffectDispatch:
        if self._payloadless_readonly_tools is not None:
            raise EffectDispatchStateError("payloadless readonly execution cannot schedule Effects")
        identity = effect_identity(tool_call, self._authority_scope)
        find_existing = getattr(self._dispatch, "find_by_ledger_key", None)
        if callable(find_existing):
            existing: EffectDispatch | None = find_existing(
                self._root_session_id, identity=identity)
            if existing is not None:
                if (
                    existing.identity != identity
                    or existing.request_hash != identity.canonical_effect_hash
                ):
                    raise EffectDispatchConflictError("effect ledger identity conflicts")
                # Business-identical replay: the stored payload is
                # authoritative — never mint a competing artifact for it.
                return existing
        if self._effect_payloads is not None:
            payload_ref = self._effect_payloads.request_artifact_ref(
                root_session_id=self._root_session_id, identity=identity
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
        if self._fresh_authority_check is not None:
            self._fresh_authority_check("effect_payload", artifact_ref)
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
        return ToolCall.model_validate_json(
            self._artifacts.read_payload_bytes(artifact_id), strict=True, extra="forbid"
        )

    def _complete(
        self, claim: EffectClaim, result: ToolResult, terminal_event: SessionEvent
    ) -> SessionEvent:
        if self._effect_payloads is not None:
            persisted = self._effect_payloads.complete_with_payload(
                claim, result=result, terminal_event=terminal_event,
                authority=self._require_mutation_authority(),
            )
            if persisted is not None:
                return persisted
        return self._dispatch.complete(claim, result=result, terminal_event=terminal_event)

    def _mark_uncertain(
        self, claim: EffectClaim, result: ToolResult, terminal_event: SessionEvent
    ) -> SessionEvent:
        evidence = uncertain_evidence(result)
        if self._effect_payloads is not None:
            persisted = self._effect_payloads.mark_uncertain_with_payload(
                claim, result=result, evidence=evidence, terminal_event=terminal_event,
                authority=self._require_mutation_authority(),
            )
            if persisted is not None:
                return persisted
        return self._dispatch.mark_uncertain(
            claim, evidence=evidence, terminal_event=terminal_event
        )

    def _fail_no_effect(
        self, claim: EffectClaim, result: ToolResult, terminal_event: SessionEvent
    ) -> SessionEvent:
        evidence = EffectEvidence(reason_code="provider_rejected_without_effect")
        if self._effect_payloads is not None:
            persisted = self._effect_payloads.fail_no_effect_with_payload(
                claim, result=result, evidence=evidence, terminal_event=terminal_event,
                authority=self._require_mutation_authority(),
            )
            if persisted is not None:
                return persisted
        return self._dispatch.fail_no_effect(
            claim, evidence=evidence, terminal_event=terminal_event
        )

    def _require_mutation_authority(self) -> WorkerMutationAuthority:
        if self._mutation_authority is None:
            raise EffectDispatchStateError("cloud Effect payload authority is unavailable")
        return self._mutation_authority()

    def _terminal_event(self, tool_call: ToolCall, result: ToolResult | None) -> SessionEvent:
        payload = effect_event_payload(tool_call)
        payload.update(
            {
                "status": ToolCallStatus.FAILED.value if result is None else result.status.value,
                "output": "" if result is None else result.output,
                "metadata": {"effect_status": "uncertain"} if result is None else result.metadata,
            }
        )
        return self._next_event(
            EventType.TOOL_EXECUTION_COMPLETED
            if result is not None and result.status is ToolCallStatus.EXECUTED
            else EventType.TOOL_EXECUTION_FAILED,
            EventActor.TOOL,
            payload,
        )
