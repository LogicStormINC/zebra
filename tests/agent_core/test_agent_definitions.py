from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain import (
    AgentDefinition,
    AgentDefinitionVersion,
    AgentRelease,
    AgentReleaseStatus,
    AgentReleaseTransitionError,
    canonical_agent_definition_digest,
)
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
    AgentReleaseId,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 3, tzinfo=UTC)
REFERENCES = {
    "model_policy_ref": "model-policy/research-default@2",
    "tool_profile_ref": "tool-profile/research-readonly@4",
    "skill_snapshot_digest": "a" * 64,
    "memory_policy_ref": "memory-policy/research@1",
    "security_policy_ref": "security-policy/external-research@3",
    "evaluation_profile_ref": "eval-profile/research@2",
    "runtime_profile_ref": "runtime-profile/gvisor@1",
}


def _definition(*, namespace_id: str = "scope-a") -> AgentDefinition:
    return AgentDefinition(
        definition_id=AgentDefinitionId(uuid4()),
        authority_issuer="https://business.example.com",
        namespace_id=namespace_id,
        name="research-agent",
        description="Bounded research",
        created_at=NOW,
    )


def _version(
    definition: AgentDefinition,
    *,
    created_at: datetime = NOW,
    definition_digest: str | None = None,
    model_policy_ref: str = REFERENCES["model_policy_ref"],
    tool_profile_ref: str = REFERENCES["tool_profile_ref"],
) -> AgentDefinitionVersion:
    return AgentDefinitionVersion.from_definition(
        definition,
        version_id=AgentDefinitionVersionId(uuid4()),
        version=1,
        created_at=created_at,
        model_policy_ref=model_policy_ref,
        tool_profile_ref=tool_profile_ref,
        skill_snapshot_digest=REFERENCES["skill_snapshot_digest"],
        memory_policy_ref=REFERENCES["memory_policy_ref"],
        security_policy_ref=REFERENCES["security_policy_ref"],
        evaluation_profile_ref=REFERENCES["evaluation_profile_ref"],
        runtime_profile_ref=REFERENCES["runtime_profile_ref"],
        definition_digest=definition_digest,
    )


def test_version_digest_is_deterministic_and_excludes_creation_time() -> None:
    definition = _definition()
    first = _version(definition, created_at=NOW)
    second = _version(definition, created_at=NOW.replace(hour=1))

    assert first.definition_digest == canonical_agent_definition_digest(first)
    assert first.definition_digest == second.definition_digest
    assert first.version_id != second.version_id


def test_digest_drift_and_unversioned_or_secret_references_fail_closed() -> None:
    definition = _definition()
    with pytest.raises(ValidationError, match="does not match"):
        _version(definition, definition_digest="b" * 64)
    with pytest.raises(ValidationError, match="versioned stable references"):
        _version(definition, tool_profile_ref="tool-profile/research")
    with pytest.raises(ValidationError, match="credentials or secrets"):
        _version(definition, model_policy_ref="model-policy/api-key@1")
    with pytest.raises(ValidationError, match="credentials or secrets"):
        _version(definition, tool_profile_ref="tool-profile/python@1")


def test_scope_mismatch_is_explicit() -> None:
    first = _definition(namespace_id="scope-a")
    second = _definition(namespace_id="scope-b")

    with pytest.raises(ValueError, match="scope mismatch"):
        first.scope.require_match(second.scope)


def test_release_lifecycle_is_ordered_and_append_only() -> None:
    version = _version(_definition())
    release = AgentRelease.from_version(
        version,
        release_id=AgentReleaseId(uuid4()),
        environment="production",
        actor_ref="publisher:operator",
        effective_at=NOW,
    )

    deprecated = release.transition(
        AgentReleaseStatus.DEPRECATED,
        revision=2,
        actor_ref="publisher:operator",
        reason_class="superseded",
        effective_at=NOW,
    )
    revoked = deprecated.transition(
        AgentReleaseStatus.REVOKED,
        revision=3,
        actor_ref="security:operator",
        reason_class="security_recall",
        effective_at=NOW,
    )

    assert release.status is AgentReleaseStatus.PUBLISHED
    assert deprecated.status is AgentReleaseStatus.DEPRECATED
    assert revoked.status is AgentReleaseStatus.REVOKED
    with pytest.raises(AgentReleaseTransitionError, match="cannot transition"):
        release.transition(
            AgentReleaseStatus.PUBLISHED,
            revision=2,
            actor_ref="publisher:operator",
            reason_class="duplicate",
            effective_at=NOW,
        )
    with pytest.raises(AgentReleaseTransitionError, match="increase by one"):
        deprecated.transition(
            AgentReleaseStatus.REVOKED,
            revision=4,
            actor_ref="security:operator",
            reason_class="security_recall",
            effective_at=NOW,
        )


def test_definition_version_and_release_are_frozen() -> None:
    version = _version(_definition())
    release = AgentRelease.from_version(
        version,
        release_id=AgentReleaseId(uuid4()),
        environment="production",
        actor_ref="publisher:operator",
        effective_at=NOW,
    )

    with pytest.raises(ValidationError):
        version.version = 2
    with pytest.raises(ValidationError):
        release.status = AgentReleaseStatus.REVOKED
