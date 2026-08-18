"""AGENT-DEF-TRUST-01 contract matrix: publication and ingress trust coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from agent_core.application.agent_definitions import PublisherGrantCeiling
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
    AgentReleaseId,
)
from agent_security.agent_definitions import (
    CrossScopeDefinitionError,
    DefinitionGrantEscalationError,
    DefinitionReferenceSubstitutionError,
    DefinitionTrustError,
    assert_no_injected_content,
    assert_no_reference_substitution,
    assert_scope_authority,
    assert_snapshot_grants_nothing,
)

CREATED = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
ISSUER = "https://issuer.example"
DIGEST = sha256(b"snapshot-content").hexdigest()
OTHER_DIGEST = sha256(b"other-content").hexdigest()


def _snapshot(**overrides: object) -> AgentDefinitionSnapshot:
    from agent_core.domain.agent_definition_snapshots import (
        BindingPurpose,
        canonical_agent_definition_snapshot_digest,
    )
    from agent_core.domain.agent_definitions import AgentReleaseStatus

    payload: dict[str, object] = {
        "definition_id": AgentDefinitionId(UUID("20000000-0000-0000-0000-000000000001")),
        "version_id": AgentDefinitionVersionId(UUID("30000000-0000-0000-0000-000000000001")),
        "definition_digest": DIGEST,
        "authority_issuer": ISSUER,
        "namespace_id": "tenant-a",
        "binding_purpose": BindingPurpose.PRODUCTION,
        "release_id": AgentReleaseId(UUID("40000000-0000-0000-0000-000000000001")),
        "release_revision": 3,
        "release_status": AgentReleaseStatus.PUBLISHED,
        "model_policy_ref": "policies/models/deepseek@v4",
        "tool_profile_ref": "policies/tools/general@v2",
        "skill_snapshot_digest": sha256(b"skills").hexdigest(),
        "memory_policy_ref": "policies/memory/workspace@v1",
        "security_policy_ref": "policies/security/strict@v3",
        "evaluation_profile_ref": "policies/evals/release@v5",
        "runtime_profile_ref": "policies/runtime/gvisor@v1",
        "resolved_at": CREATED,
    }
    payload.update(overrides)
    constructed = AgentDefinitionSnapshot.model_construct(**dict(payload))
    digest = canonical_agent_definition_snapshot_digest(constructed)
    return AgentDefinitionSnapshot.model_validate(
        constructed.model_copy(update={"snapshot_digest": digest}).model_dump()
    )


def _ceiling(namespace_id: str = "tenant-a") -> PublisherGrantCeiling:
    return PublisherGrantCeiling(
        authority_issuer=ISSUER,
        namespace_id=namespace_id,
        allowed_references=frozenset(),
    )


def test_content_trust_never_grants_capability() -> None:
    snapshot = _snapshot()
    assert_snapshot_grants_nothing(snapshot)
    escalating = _snapshot(
        tool_profile_ref="policies/tools/allow-all@v1",
    )
    with pytest.raises(DefinitionGrantEscalationError):
        assert_snapshot_grants_nothing(escalating)
    bypass = _snapshot(
        security_policy_ref="policies/security/bypass@v1",
    )
    with pytest.raises(DefinitionGrantEscalationError):
        assert_snapshot_grants_nothing(bypass)


def test_cross_namespace_and_missing_grant_fail_closed() -> None:
    with pytest.raises(CrossScopeDefinitionError):
        assert_scope_authority("tenant-a", None)
    with pytest.raises(CrossScopeDefinitionError):
        assert_scope_authority("tenant-a", _ceiling(namespace_id="tenant-b"))
    assert_scope_authority("tenant-a", _ceiling())


def test_reference_substitution_fails_closed() -> None:
    snapshot = _snapshot()
    assert_no_reference_substitution(snapshot, version_digest=DIGEST)
    with pytest.raises(DefinitionReferenceSubstitutionError):
        assert_no_reference_substitution(snapshot, version_digest=OTHER_DIGEST)


def test_prompt_injection_markers_fail_closed() -> None:
    assert_no_injected_content(_snapshot())
    injected = _snapshot(
        model_policy_ref="policies/models/ignore-previous-instructions@v1",
    )
    with pytest.raises(DefinitionTrustError):
        assert_no_injected_content(injected)
    injected_scope = _snapshot(
        namespace_id="tenant-a",
    )
    assert_no_injected_content(injected_scope)


def test_independent_authority_tracing_shape() -> None:
    """Publisher grant, snapshot and Attempt authority are separate inputs."""
    scope = AgentDefinitionScope(
        authority_issuer=ISSUER,
        namespace_id="tenant-a",
        definition_id=AgentDefinitionId(
            UUID("20000000-0000-0000-0000-000000000001")
        ),
    )
    assert scope.authority_issuer == ISSUER
    snapshot = _snapshot()
    assert snapshot.authority_issuer == scope.authority_issuer
    assert snapshot.namespace_id == scope.namespace_id
    # a snapshot is never an execution grant: binding it changes no authority
    assert "grant" not in snapshot.model_dump(mode="json")
