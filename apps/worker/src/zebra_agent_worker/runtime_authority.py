import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthorityLimits,
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityResolutionRequest,
    ExecutionAuthorityRevalidation,
    ExecutionAuthorityRevalidationRequest,
    ExecutionAuthoritySnapshot,
    ExternalAuthorityGrant,
)
from agent_core.domain.identifiers import SessionId
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.execution_authority import ExecutionAuthorityResolverPort
from agent_core.ports.runtime import EffectiveRuntimeAuthority

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


class ClosableToolGateway(Protocol):
    def close(self) -> None: ...


class FailClosedExternalAuthorityResolver:
    """Default external boundary until a verifier adapter is configured."""

    def resolve_for_attempt(
        self,
        request: ExecutionAuthorityResolutionRequest,
    ) -> ExecutionAuthoritySnapshot:
        del request
        raise ExecutionAuthorityResolutionError(
            "external execution authority verifier is not configured"
        )

    def revalidate_attempt(
        self,
        request: ExecutionAuthorityRevalidationRequest,
    ) -> ExecutionAuthorityRevalidation:
        del request
        raise ExecutionAuthorityResolutionError(
            "external execution authority verifier is not configured"
        )


@dataclass(frozen=True)
class TrustedLocalExecutionAuthorityResolver:
    """Explicit local-only authority; it never infers scope from runtime state."""

    authority_issuer: str
    namespace_id: str
    policy_ref: str
    policy_version: str
    policy_effective_digest: str
    subject: str = "trusted-local"
    audience: str = "zebra"
    granted_authorities: tuple[str, ...] = ("agent.execute",)
    limits: ExecutionAuthorityLimits = ExecutionAuthorityLimits(
        max_concurrent_tasks=1,
        max_model_tokens=200_000,
        max_runtime_seconds=3_600,
        max_tool_calls=1_000,
    )
    lifetime_seconds: int = 900

    def __post_init__(self) -> None:
        if self.lifetime_seconds <= 0:
            raise ValueError("trusted local authority lifetime must be positive")
        OpaqueAuthorityScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
        )

    @property
    def scope(self) -> OpaqueAuthorityScope:
        return OpaqueAuthorityScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
        )

    def resolve_for_attempt(
        self,
        request: ExecutionAuthorityResolutionRequest,
    ) -> ExecutionAuthoritySnapshot:
        self._require_scope(request.scope)
        grant = self._grant(
            issued_at=request.validated_at,
            expires_at=request.validated_at + timedelta(seconds=self.lifetime_seconds),
        )
        return ExecutionAuthoritySnapshot.from_request(
            request.model_copy(update={"authority_grant": grant}),
            policy_ref=self.policy_ref,
            policy_version=self.policy_version,
            policy_effective_digest=self.policy_effective_digest,
        )

    def revalidate_attempt(
        self,
        request: ExecutionAuthorityRevalidationRequest,
    ) -> ExecutionAuthorityRevalidation:
        self._require_scope(request.scope)
        if request.validated_at >= request.prior_snapshot.expires_at:
            return ExecutionAuthorityRevalidation(
                attempt_number=request.attempt_number,
                prior_snapshot_digest=request.prior_snapshot.snapshot_digest or "",
                source_authority_digest=self._source_digest(),
                decision=ExecutionAuthorityDecision.EXPIRED,
                validated_at=request.validated_at,
                reason_code="authority_expired",
            )
        expires_at = min(
            request.prior_snapshot.expires_at,
            request.validated_at + timedelta(seconds=self.lifetime_seconds),
        )
        replacement = ExecutionAuthoritySnapshot.from_request(
            ExecutionAuthorityResolutionRequest(
                session_id=request.session_id,
                attempt_number=request.attempt_number,
                scope=request.scope,
                authority_grant=self._grant(
                    issued_at=request.prior_snapshot.issued_at,
                    expires_at=expires_at,
                ),
                agent_definition_snapshot_digest=(
                    request.prior_snapshot.agent_definition_snapshot_digest
                ),
                capability_ceiling=request.capability_ceiling,
                validated_at=request.validated_at,
            ),
            policy_ref=self.policy_ref,
            policy_version=self.policy_version,
            policy_effective_digest=self.policy_effective_digest,
        )
        request.prior_snapshot.ensure_not_expanded(replacement)
        return ExecutionAuthorityRevalidation(
            attempt_number=request.attempt_number,
            prior_snapshot_digest=request.prior_snapshot.snapshot_digest or "",
            source_authority_digest=replacement.source_authority_digest,
            effective_snapshot_digest=replacement.snapshot_digest,
            decision=replacement.resolution,
            validated_at=request.validated_at,
            expires_at=replacement.expires_at,
            effective_snapshot=replacement,
        )

    def _grant(self, *, issued_at: datetime, expires_at: datetime) -> ExternalAuthorityGrant:
        return ExternalAuthorityGrant(
            scope=self.scope,
            subject=self.subject,
            audience=self.audience,
            granted_authorities=self.granted_authorities,
            limits=self.limits,
            issued_at=issued_at,
            expires_at=expires_at,
            source_authority_digest=self._source_digest(),
        )

    def _source_digest(self) -> str:
        payload = {
            "audience": self.audience,
            "authority_issuer": self.authority_issuer,
            "granted_authorities": tuple(sorted(self.granted_authorities)),
            "namespace_id": self.namespace_id,
            "subject": self.subject,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _require_scope(self, scope: OpaqueAuthorityScope) -> None:
        if scope != self.scope:
            raise ExecutionAuthorityResolutionError(
                "trusted local resolver scope does not match requested scope"
            )


def persist_attempt_authority(
    recorder: DurableHarnessEventRecorder,
    resolver: ExecutionAuthorityResolverPort | None,
    scope: OpaqueAuthorityScope | None,
    *,
    session_id: SessionId,
    existing_events: tuple[SessionEvent, ...] | list[SessionEvent],
    attempt_number: int,
    created_at: datetime,
) -> bool:
    """Persist authority evidence before an Attempt starts or resumes."""

    if resolver is None:
        return False
    if scope is None:
        raise ExecutionAuthorityResolutionError(
            "an explicit authority scope is required when a resolver is configured"
        )
    assert resolver is not None
    request = ExecutionAuthorityResolutionRequest(
        session_id=session_id,
        attempt_number=attempt_number,
        scope=scope,
        validated_at=created_at,
    )
    prior = _latest_authority_snapshot(existing_events)
    if prior is None:
        snapshot = resolver.resolve_for_attempt(request)
        _validate_snapshot(snapshot, request)
        recorder.append(
            EventType.EXECUTION_AUTHORITY_RESOLVED,
            EventActor.SYSTEM,
            snapshot.to_event_payload(),
            created_at=created_at,
        )
        return True

    revalidation = resolver.revalidate_attempt(
        ExecutionAuthorityRevalidationRequest(
            session_id=session_id,
            attempt_number=attempt_number,
            scope=scope,
            prior_snapshot=prior,
            validated_at=created_at,
        )
    )
    if revalidation.prior_snapshot_digest != prior.snapshot_digest:
        raise ExecutionAuthorityResolutionError(
            "authority revalidation does not reference the durable snapshot"
        )
    if revalidation.effective_snapshot is not None:
        prior.ensure_not_expanded(revalidation.effective_snapshot)
    elif revalidation.decision in {
        ExecutionAuthorityDecision.ALLOWED,
        ExecutionAuthorityDecision.NARROWED,
    }:
        raise ExecutionAuthorityResolutionError(
            "accepted authority revalidation did not return effective evidence"
        )
    recorder.append(
        EventType.EXECUTION_AUTHORITY_REVALIDATED,
        EventActor.SYSTEM,
        revalidation.to_event_payload(),
        created_at=created_at,
    )
    if revalidation.decision not in {
        ExecutionAuthorityDecision.ALLOWED,
        ExecutionAuthorityDecision.NARROWED,
    }:
        raise ExecutionAuthorityResolutionError(
            f"authority revalidation denied Attempt: {revalidation.decision.value}"
        )
    return True


def _latest_authority_snapshot(
    events: tuple[SessionEvent, ...] | list[SessionEvent],
) -> ExecutionAuthoritySnapshot | None:
    latest: ExecutionAuthoritySnapshot | None = None
    for event in events:
        if event.event_type is EventType.EXECUTION_AUTHORITY_RESOLVED:
            try:
                latest = ExecutionAuthoritySnapshot.model_validate(event.payload)
            except ValueError as exc:
                raise ExecutionAuthorityResolutionError(
                    "durable authority snapshot is invalid"
                ) from exc
            continue
        if event.event_type is not EventType.EXECUTION_AUTHORITY_REVALIDATED:
            continue
        try:
            revalidation = ExecutionAuthorityRevalidation.model_validate(event.payload)
        except ValueError as exc:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation is invalid"
            ) from exc
        if revalidation.decision not in {
            ExecutionAuthorityDecision.ALLOWED,
            ExecutionAuthorityDecision.NARROWED,
        }:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation denied the Attempt"
            )
        if latest is None or revalidation.prior_snapshot_digest != latest.snapshot_digest:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation has no matching prior snapshot"
            )
        if revalidation.effective_snapshot is None:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation has no recoverable effective snapshot"
            )
        latest.ensure_not_expanded(revalidation.effective_snapshot)
        latest = revalidation.effective_snapshot
    return latest


def _validate_snapshot(
    snapshot: ExecutionAuthoritySnapshot,
    request: ExecutionAuthorityResolutionRequest,
) -> None:
    if snapshot.attempt_number != request.attempt_number:
        raise ExecutionAuthorityResolutionError(
            "resolved authority snapshot attempt number does not match"
        )
    if snapshot.scope != request.scope:
        raise ExecutionAuthorityResolutionError("resolved authority snapshot scope does not match")


def persist_runtime_authority(
    recorder: DurableHarnessEventRecorder,
    authority: EffectiveRuntimeAuthority | None,
    *,
    created_at: datetime,
) -> bool:
    if authority is None or recorder.workspace.runtime_spec_digest == authority.spec_digest:
        return False
    recorder.append(
        EventType.RUNTIME_PROVISIONED,
        EventActor.SYSTEM,
        {
            "runtime_class": authority.runtime_class.value,
            "engine": authority.engine,
            "image": authority.image,
            "spec_digest": authority.spec_digest,
            "network_enforcement": authority.network_enforcement,
            "workspace_writable": authority.workspace_writable,
        },
        created_at=created_at,
    )
    return True


def close_tool_gateway(tool_gateway: ClosableToolGateway) -> Exception | None:
    try:
        tool_gateway.close()
    except Exception as exc:
        return exc
    return None


def runtime_cleanup_failure_result(
    error: Exception,
    prior: HarnessAttemptResult,
) -> HarnessAttemptResult:
    return HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="runtime cleanup failed",
        metadata={
            "stop_reason": "runtime_cleanup_failed",
            "error_type": type(error).__name__,
            "model_calls_used": prior.metadata.get("model_calls_used", 0),
            "tool_calls_executed": prior.metadata.get("tool_calls_executed", 0),
        },
    )
