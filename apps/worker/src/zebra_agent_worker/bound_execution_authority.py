"""Attempt authority bound to the immutable Task binding (AL-AUTH-WORKER-01).

P0.4: the HTTP HostGrant chain and the Worker authority chain become one.
Instead of the deployment-level synthetic ``agent.execute`` authority, the
resolver derives every Attempt's ``ExecutionAuthoritySnapshot`` from the
admission-frozen ``TaskBindingSnapshot``: issuer and namespace are pinned to
the Host capability snapshot, the Definition digest and capability ceiling
come from the binding, and Zebra policy evidence is the binding's policy
digest. Drift, expiry and revocation fail closed; revalidation can only
narrow.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
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
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.execution_authority import (
    ExecutionAuthorityResolverPort,
)


@dataclass(frozen=True)
class BoundHostExecutionAuthorityResolver(ExecutionAuthorityResolverPort):
    """One Task binding -> one narrowable Attempt authority chain."""

    binding: TaskBindingSnapshot
    policy_ref: str = "policy/task-binding@1"
    policy_version: str = "1"
    subject: str = "bound-host"
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
            raise ValueError("bound host authority lifetime must be positive")

    @property
    def scope(self) -> OpaqueAuthorityScope:
        host = self.binding.host_capability
        return OpaqueAuthorityScope(
            authority_issuer=host.authority_issuer,
            namespace_id=host.namespace_id,
        )

    def resolve_for_attempt(
        self,
        request: ExecutionAuthorityResolutionRequest,
    ) -> ExecutionAuthoritySnapshot:
        self._fail_closed_checks(request.scope, request.validated_at)
        grant = self._grant(
            issued_at=request.validated_at,
            expires_at=request.validated_at + timedelta(seconds=self.lifetime_seconds),
        )
        return ExecutionAuthoritySnapshot.from_request(
            request.model_copy(
                update={
                    "authority_grant": grant,
                    "agent_definition_snapshot_digest": (
                        self.binding.agent_capability_ceiling.definition_snapshot_digest
                    ),
                    "capability_ceiling": tuple(
                        sorted(self.binding.effective_capabilities)
                    ),
                }
            ),
            policy_ref=self.policy_ref,
            policy_version=self.policy_version,
            policy_effective_digest=self.binding.zebra_policy_digest,
        )

    def revalidate_attempt(
        self,
        request: ExecutionAuthorityRevalidationRequest,
    ) -> ExecutionAuthorityRevalidation:
        self._fail_closed_checks(request.scope, request.validated_at)
        binding_expiry = self.binding.host_capability.grant_expires_at
        hard_expiry = request.prior_snapshot.expires_at
        if binding_expiry is not None:
            hard_expiry = min(hard_expiry, binding_expiry)
        if request.validated_at >= hard_expiry:
            return ExecutionAuthorityRevalidation(
                attempt_number=request.attempt_number,
                prior_snapshot_digest=request.prior_snapshot.snapshot_digest or "",
                source_authority_digest=self._source_digest(),
                decision=ExecutionAuthorityDecision.EXPIRED,
                validated_at=request.validated_at,
                reason_code="bound_authority_expired",
            )
        expires_at = min(
            hard_expiry,
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
                agent_definition_snapshot_digest=request.prior_snapshot.agent_definition_snapshot_digest,
                capability_ceiling=tuple(sorted(self.binding.effective_capabilities)),
                validated_at=request.validated_at,
            ),
            policy_ref=self.policy_ref,
            policy_version=self.policy_version,
            policy_effective_digest=self.binding.zebra_policy_digest,
        )
        request.prior_snapshot.ensure_not_expanded(replacement)
        return ExecutionAuthorityRevalidation(
            attempt_number=request.attempt_number,
            prior_snapshot_digest=request.prior_snapshot.snapshot_digest or "",
            source_authority_digest=self._source_digest(),
            decision=ExecutionAuthorityDecision.NARROWED,
            validated_at=request.validated_at,
            effective_snapshot=replacement,
            effective_snapshot_digest=replacement.snapshot_digest,
            expires_at=replacement.expires_at,
        )

    def _grant(
        self, *, issued_at: datetime, expires_at: datetime
    ) -> ExternalAuthorityGrant:
        return ExternalAuthorityGrant(
            scope=self.scope,
            subject=self.subject,
            audience=self.audience,
            granted_authorities=self.granted_authorities,
            limits=self.limits,
            issued_at=issued_at,
            expires_at=expires_at,
            source_authority_digest=self._source_digest(),
            revoked=False,
        )

    def _source_digest(self) -> str:
        return self.binding.binding_digest[:64]

    def _fail_closed_checks(
        self,
        scope: OpaqueAuthorityScope,
        validated_at: datetime,
    ) -> None:
        host = self.binding.host_capability
        if scope.authority_issuer != host.authority_issuer:
            raise ExecutionAuthorityResolutionError(
                "bound authority issuer does not match the Task binding; failing closed"
            )
        if scope.namespace_id != host.namespace_id:
            raise ExecutionAuthorityResolutionError(
                "bound authority namespace drifted from the Task binding; failing closed"
            )
        expiry = host.grant_expires_at
        if expiry is not None and validated_at >= expiry:
            raise ExecutionAuthorityResolutionError(
                "bound Host grant has expired; failing closed"
            )


def select_attempt_authority(
    resolver: ExecutionAuthorityResolverPort | None,
    static_scope: OpaqueAuthorityScope | None,
    scope_provider: Callable[..., OpaqueAuthorityScope] | None,
    task_binding_loader: Callable[..., object] | None,
    session_id: object,
) -> tuple[
    ExecutionAuthorityResolverPort | None,
    OpaqueAuthorityScope | None,
    Callable[..., OpaqueAuthorityScope] | None,
]:
    """Phase F1: a frozen Task binding drives this Attempt's authority.

    The deployment resolver/scope stay the fallback when no binding is
    stored for the session; loader failures fall back the same way.
    """

    if task_binding_loader is None:
        return resolver, static_scope, scope_provider
    try:
        loaded = task_binding_loader(session_id)
    except Exception:
        return resolver, static_scope, scope_provider
    if not isinstance(loaded, TaskBindingSnapshot):
        return resolver, static_scope, scope_provider
    binding = loaded
    scope = OpaqueAuthorityScope(
        authority_issuer=binding.host_capability.authority_issuer,
        namespace_id=binding.host_capability.namespace_id,
    )
    return BoundHostExecutionAuthorityResolver(binding=binding), scope, None
