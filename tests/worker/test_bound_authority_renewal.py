"""A verified new command renews authority; replaying old evidence does not."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityResolutionRequest,
)
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import SessionId
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api.session_binding import _build_binding_snapshot, renew_task_binding_snapshot
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.runtime_authority import persist_attempt_authority

NOW = datetime(2026, 9, 5, 10, tzinfo=UTC)


def _context(*, grant_id, expires_at=None):
    return HostContextEnvelope(
        grant_id=grant_id,
        host_app_id="trench",
        namespace_id="trench:user-1",
        workspace_ref="trench-workspace:user-1",
        resource_refs=(HostResourceRef(type="principal", id="user-1"),),
        scopes=("agent.run",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300, max_model_tokens=10000, max_artifact_bytes=1000000
        ),
        origin="https://trench.local",
        policy_version="trench-native-v2",
        expires_at=expires_at or NOW + timedelta(minutes=5),
    )


def _case():
    context = _context(grant_id="first")
    binding = _build_binding_snapshot(
        "11111111-1111-1111-1111-111111111111",
        host_context=context,
        verified_host_grant=VerifiedHostGrant(
            context, context.grant_id, JwtAlgorithm.RS256, context.origin, "user-1"
        ),
        definition_snapshot_digest="a" * 64,
    )
    resolver = BoundHostExecutionAuthorityResolver(binding)
    request = ExecutionAuthorityResolutionRequest(
        session_id=SessionId(UUID(binding.task_id)),
        attempt_number=1,
        scope=resolver.scope,
        validated_at=NOW,
    )
    prior = resolver.resolve_for_attempt(request)
    later = NOW + timedelta(hours=1)
    renewed = renew_task_binding_snapshot(
        binding,
        _context(grant_id="second", expires_at=later + timedelta(minutes=5)),
        bound_at=later,
    )
    return resolver, prior, request.model_copy(update={"validated_at": later}), renewed


def test_new_verified_binding_resolves_after_old_expiry(monkeypatch):
    _, prior, request, renewed = _case()
    resolver = BoundHostExecutionAuthorityResolver(renewed)
    snapshot = resolver.resolve_renewed_binding(request, prior)
    assert snapshot is not None
    assert snapshot.expires_at == renewed.host_capability.grant_expires_at
    assert snapshot.expires_at > prior.expires_at
    assert resolver.resolve_renewed_binding(request, snapshot) is None
    recorder = Mock()
    monkeypatch.setattr(
        "zebra_agent_worker.runtime_authority._latest_authority_snapshot", lambda _: prior
    )
    assert persist_attempt_authority(
        recorder,
        resolver,
        resolver.scope,
        session_id=request.session_id,
        existing_events=[],
        attempt_number=1,
        created_at=request.validated_at,
    )
    assert recorder.append.call_args.args[0] == EventType.EXECUTION_AUTHORITY_RESOLVED


def test_initial_authority_cannot_outlive_host_grant():
    resolver, prior, _, _ = _case()
    assert prior.expires_at == resolver.binding.host_capability.grant_expires_at


def test_unchanged_binding_cannot_renew():
    resolver, prior, request, _ = _case()
    assert resolver.resolve_renewed_binding(request, prior) is None


def test_expired_fresh_binding_fails_closed():
    _, prior, request, renewed = _case()
    request = request.model_copy(update={"validated_at": request.validated_at + timedelta(hours=1)})
    with pytest.raises(ExecutionAuthorityResolutionError, match="expired"):
        BoundHostExecutionAuthorityResolver(renewed).resolve_renewed_binding(request, prior)


def test_changed_policy_cannot_renew():
    _, prior, request, renewed = _case()
    renewed = renewed.model_copy(update={"zebra_policy_digest": "1" * 64})
    with pytest.raises(ExecutionAuthorityResolutionError, match="ceilings"):
        BoundHostExecutionAuthorityResolver(renewed).resolve_renewed_binding(request, prior)


@pytest.mark.parametrize(
    "change",
    [
        {"namespace_id": "another-user"},
        {"agent_definition_snapshot_digest": "2" * 64},
        {"granted_authorities": ()},
    ],
)
def test_renewal_preserves_prior_identity_and_capabilities(change):
    _, prior, request, renewed = _case()
    with pytest.raises(ExecutionAuthorityResolutionError, match="ceilings"):
        BoundHostExecutionAuthorityResolver(renewed).resolve_renewed_binding(
            request,
            prior.model_copy(update=change),
        )
