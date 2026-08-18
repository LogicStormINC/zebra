"""Bound host execution authority tests: one chain, fail-closed semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityResolutionRequest,
    ExecutionAuthorityRevalidationRequest,
)
from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from zebra_agent_worker.bound_execution_authority import (
    BoundHostExecutionAuthorityResolver,
)

TASK_ID = "task-bound-1"
ISSUER = "https://host-a.example.com"
NAMESPACE = "tenant-a"


def _binding(
    *,
    expires_at: datetime | None = None,
    capabilities: frozenset | None = None,
) -> TaskBindingSnapshot:
    caps = capabilities if capabilities is not None else capability_set(
        ["agent.execute", "evidence.read"]
    )
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/default@1",
        capabilities=caps,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-a",
        authority_issuer=ISSUER,
        namespace_id=NAMESPACE,
        grant_digest="c" * 64,
        grant_expires_at=expires_at,
        connector_id="host-a-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=caps,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=TASK_ID,
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=caps,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def _request(
    scope: OpaqueAuthorityScope, *, number: int = 1
) -> ExecutionAuthorityResolutionRequest:
    import uuid

    return ExecutionAuthorityResolutionRequest(
        session_id=SessionId(uuid.uuid4()),
        attempt_number=number,
        scope=scope,
        validated_at=datetime.now(UTC),
    )


def _scope(issuer: str = ISSUER, namespace: str = NAMESPACE) -> OpaqueAuthorityScope:
    return OpaqueAuthorityScope(authority_issuer=issuer, namespace_id=namespace)


class TestResolveForAttempt:
    def test_snapshot_carries_the_binding_chain(self) -> None:
        resolver = BoundHostExecutionAuthorityResolver(binding=_binding())
        snapshot = resolver.resolve_for_attempt(_request(_scope()))
        assert set(snapshot.granted_authorities) <= {"agent.execute", "evidence.read"}
        assert snapshot.granted_authorities == ("agent.execute",)
        assert snapshot.namespace_id == NAMESPACE
        assert snapshot.authority_issuer == ISSUER

    def test_namespace_drift_fails_closed(self) -> None:
        resolver = BoundHostExecutionAuthorityResolver(binding=_binding())
        with pytest.raises(ExecutionAuthorityResolutionError, match="namespace drifted"):
            resolver.resolve_for_attempt(_request(_scope(namespace="tenant-b")))

    def test_issuer_mismatch_fails_closed(self) -> None:
        resolver = BoundHostExecutionAuthorityResolver(binding=_binding())
        with pytest.raises(ExecutionAuthorityResolutionError, match="issuer"):
            resolver.resolve_for_attempt(_request(_scope(issuer="https://other")))

    def test_expired_grant_fails_closed(self) -> None:
        expired = _binding(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        resolver = BoundHostExecutionAuthorityResolver(binding=expired)
        with pytest.raises(ExecutionAuthorityResolutionError, match="expired"):
            resolver.resolve_for_attempt(_request(_scope()))


class TestRevalidateAttempt:
    def test_revalidation_only_narrows(self) -> None:
        resolver = BoundHostExecutionAuthorityResolver(binding=_binding())
        first = resolver.resolve_for_attempt(_request(_scope()))
        later = ExecutionAuthorityRevalidationRequest(
            session_id=_request(_scope()).session_id,
            attempt_number=1,
            scope=_scope(),
            prior_snapshot=first,
            validated_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        outcome = resolver.revalidate_attempt(later)
        assert outcome.decision.value in {"narrowed", "revalidated", "unchanged"}

    def test_revalidation_after_grant_expiry_is_expired(self) -> None:
        resolver = BoundHostExecutionAuthorityResolver(binding=_binding())
        first = resolver.resolve_for_attempt(_request(_scope()))
        later = ExecutionAuthorityRevalidationRequest(
            session_id=_request(_scope()).session_id,
            attempt_number=1,
            scope=_scope(),
            prior_snapshot=first,
            validated_at=datetime.now(UTC) + timedelta(hours=2),
        )
        outcome = resolver.revalidate_attempt(later)
        assert outcome.decision.value == "expired"

    def test_revalidation_drift_fails_closed(self) -> None:
        resolver = BoundHostExecutionAuthorityResolver(binding=_binding())
        first = resolver.resolve_for_attempt(_request(_scope()))
        with pytest.raises(ValueError, match="drifted|does not match"):

            def _drifted() -> None:
                later = ExecutionAuthorityRevalidationRequest(
                    session_id=_request(_scope()).session_id,
                    attempt_number=1,
                    scope=_scope(namespace="other"),
                    prior_snapshot=first,
                    validated_at=datetime.now(UTC),
                )
                resolver.revalidate_attempt(later)

            _drifted()
