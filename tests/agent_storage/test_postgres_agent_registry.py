"""Real PostgreSQL coverage for the Agent Definition Registry (v19)."""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionScope,
    AgentDefinitionVersion,
    AgentRelease,
    AgentReleaseStatus,
)
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
    AgentReleaseId,
)
from agent_storage import (
    AgentDefinitionEvalEvidence,
    AgentRegistryStorageError,
    PostgresAgentRegistry,
    apply_postgres_migrations,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

DIGEST = sha256(b"skill-snapshot").hexdigest()
CREATED = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"agent_registry_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _registry(dsn: str) -> PostgresAgentRegistry:
    return PostgresAgentRegistry(dsn, deployment_namespace="cloud-a")


def _definition(definition_id: AgentDefinitionId | None = None) -> AgentDefinition:
    return AgentDefinition(
        definition_id=definition_id or AgentDefinitionId(uuid4()),
        authority_issuer="https://issuer.example",
        namespace_id="tenant-a",
        name="code-agent",
        description="Primary coding agent",
        revision=0,
        created_at=CREATED,
    )


def _version(definition: AgentDefinition) -> AgentDefinitionVersion:
    return AgentDefinitionVersion.from_definition(
        definition,
        version_id=AgentDefinitionVersionId(uuid4()),
        version=1,
        created_at=CREATED,
        model_policy_ref="policies/models/deepseek@v4",
        tool_profile_ref="policies/tools/general@v2",
        skill_snapshot_digest=DIGEST,
        memory_policy_ref="policies/memory/workspace@v1",
        security_policy_ref="policies/security/strict@v3",
        evaluation_profile_ref="policies/evals/release@v5",
        runtime_profile_ref="policies/runtime/gvisor@v1",
    )


def test_definition_roundtrip_with_revision_cas(dsn: str) -> None:
    registry = _registry(dsn)
    definition = _definition()
    saved = registry.save_definition(definition)
    assert saved.revision == 0
    renamed = definition.model_copy(update={"name": "code-agent-2"})
    updated = registry.save_definition(renamed, expected_revision=0)
    assert updated.revision == 1
    assert updated.name == "code-agent-2"
    with pytest.raises(AgentRegistryStorageError, match="revision conflict"):
        registry.save_definition(renamed, expected_revision=0)
    fetched = registry.get_definition(definition.scope)
    assert fetched == updated


def test_versions_are_immutable_and_digest_unique(dsn: str) -> None:
    registry = _registry(dsn)
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    fetched = registry.get_version(definition.scope, version.version_id)
    assert fetched == version
    replayed = registry.save_version(version)
    assert replayed.definition_digest == version.definition_digest
    with pytest.raises(AgentRegistryStorageError, match="version number"):
        registry.save_version(
            _version(definition).model_copy(
                update={
                    "version_id": AgentDefinitionVersionId(uuid4()),
                    "model_policy_ref": "policies/models/other@v1",
                }
            )
        )


def test_publish_supersedes_and_resolves_single(dsn: str) -> None:
    registry = _registry(dsn)
    definition = registry.save_definition(_definition())
    first_version = registry.save_version(_version(definition))
    second_version = registry.save_version(
        _version(definition).model_copy(
            update={
                "version_id": AgentDefinitionVersionId(uuid4()),
                "version": 2,
                "model_policy_ref": "policies/models/deepseek@v5",
            }
        )
    )
    first_release = registry.append_release(
        AgentRelease.from_version(
            first_version,
            release_id=AgentReleaseId(uuid4()),
            environment="production",
            actor_ref="release-bot@example",
            effective_at=CREATED,
        )
    )
    resolved = registry.resolve_published(definition.scope, environment="production")
    assert resolved is not None and resolved.version_id == first_version.version_id
    second_release = registry.append_release(
        AgentRelease.from_version(
            second_version,
            release_id=AgentReleaseId(uuid4()),
            environment="production",
            actor_ref="release-bot@example",
            effective_at=CREATED,
        )
    )
    assert second_release.revision == 3
    resolved = registry.resolve_published(definition.scope, environment="production")
    assert resolved is not None
    assert resolved.version_id == second_version.version_id
    assert resolved.definition_digest == second_version.definition_digest
    assert first_release.revision == 1
    deprecate = registry.append_release(
        second_release.transition(
            AgentReleaseStatus.DEPRECATED,
            revision=second_release.revision + 1,
            actor_ref="release-bot@example",
            reason_class="rollback",
            effective_at=CREATED,
        )
    )
    assert deprecate.status is AgentReleaseStatus.DEPRECATED
    assert registry.resolve_published(definition.scope, environment="production") is None


def test_draft_cas_roundtrip_and_validation_evidence(dsn: str) -> None:
    from agent_core.domain.agent_definition_drafts import (
        AgentDefinitionDraft,
        AgentDefinitionDraftValidation,
        AgentDraftValidationIssue,
        AgentDraftValidationStatus,
    )

    registry = _registry(dsn)
    definition = registry.save_definition(_definition())
    draft = AgentDefinitionDraft(
        definition_id=definition.definition_id,
        authority_issuer=definition.authority_issuer,
        namespace_id=definition.namespace_id,
        name="code-agent",
        description="draft payload",
        model_policy_ref="policies/models/deepseek@v4",
        tool_profile_ref="policies/tools/general@v2",
        skill_snapshot_digest=DIGEST,
        memory_policy_ref="policies/memory/workspace@v1",
        security_policy_ref="policies/security/strict@v3",
        evaluation_profile_ref="policies/evals/release@v5",
        runtime_profile_ref="policies/runtime/gvisor@v1",
        revision=0,
        updated_at=CREATED,
    )
    saved = registry.save_draft(draft)
    assert saved.revision == 0
    assert registry.get_draft(definition.scope) == saved
    with pytest.raises(AgentRegistryStorageError, match="revision conflict"):
        registry.save_draft(draft, expected_revision=1)
    updated = registry.save_draft(
        draft.model_copy(update={"description": "v2", "revision": 1}),
        expected_revision=0,
    )
    assert registry.get_draft(definition.scope) == updated
    validation = AgentDefinitionDraftValidation(
        definition_id=definition.definition_id,
        authority_issuer=definition.authority_issuer,
        namespace_id=definition.namespace_id,
        validation_id=uuid4(),
        draft_revision=1,
        status=AgentDraftValidationStatus.FAILED,
        issues=(
            AgentDraftValidationIssue(
                code="reference-not-granted",
                field="model_policy_ref",
                message="outside grant",
            ),
        ),
        evaluated_at=CREATED,
        evaluator_actor="eval-bot@example",
    )
    registry.append_draft_validation(validation)
    registry.append_draft_validation(validation)
    latest = registry.latest_draft_validation(definition.scope)
    assert latest == validation
    passed = validation.model_copy(
        update={
            "validation_id": uuid4(),
            "status": AgentDraftValidationStatus.PASSED,
            "issues": (),
        }
    )
    registry.append_draft_validation(passed)
    assert registry.latest_draft_validation(definition.scope) == passed


def test_draft_service_materializes_only_validated_drafts(dsn: str) -> None:
    from agent_core.application.agent_definitions import (
        AgentDefinitionDraftService,
        AgentDefinitionDraftServiceError,
        DraftNotValidatedError,
        DraftValidationFailedError,
        MissingPublisherGrantError,
        PublisherGrantCeiling,
        StaticPublisherGrantResolver,
    )

    registry = _registry(dsn)
    definition = registry.save_definition(_definition())
    grants = StaticPublisherGrantResolver(
        {
            "publisher-b@tenant-a": PublisherGrantCeiling(
                authority_issuer=definition.authority_issuer,
                namespace_id="tenant-a",
                allowed_references=frozenset(
                    {
                        "policies/models/deepseek@v4",
                        "policies/tools/general@v2",
                        "policies/memory/workspace@v1",
                        "policies/security/strict@v3",
                        "policies/evals/release@v5",
                        "policies/runtime/gvisor@v1",
                    }
                ),
            )
        }
    )
    service = AgentDefinitionDraftService(registry, grants)
    with pytest.raises(MissingPublisherGrantError):
        service.create_draft(
            definition_id=definition.definition_id,
            namespace_id="tenant-a",
            actor_ref="unknown@example",
            name="code-agent",
            description="",
            model_policy_ref="policies/models/deepseek@v4",
            tool_profile_ref="policies/tools/general@v2",
            skill_snapshot_digest=DIGEST,
            memory_policy_ref="policies/memory/workspace@v1",
            security_policy_ref="policies/security/strict@v3",
            evaluation_profile_ref="policies/evals/release@v5",
            runtime_profile_ref="policies/runtime/gvisor@v1",
            updated_at=CREATED,
        )
    draft = service.create_draft(
        definition_id=definition.definition_id,
        namespace_id="tenant-a",
        actor_ref="publisher-b",
        name="code-agent",
        description="",
        model_policy_ref="policies/models/deepseek@v5",
        tool_profile_ref="policies/tools/general@v2",
        skill_snapshot_digest=DIGEST,
        memory_policy_ref="policies/memory/workspace@v1",
        security_policy_ref="policies/security/strict@v3",
        evaluation_profile_ref="policies/evals/release@v5",
        runtime_profile_ref="policies/runtime/gvisor@v1",
        updated_at=CREATED,
    )
    assert draft.revision == 0
    with pytest.raises(AgentDefinitionDraftServiceError, match="revision conflict"):
        service.update_draft(
            definition_id=definition.definition_id,
            namespace_id="tenant-a",
            actor_ref="publisher-b",
            expected_revision=1,
            updated_at=CREATED,
            description="v2",
        )
    with pytest.raises(DraftNotValidatedError):
        service.materialize_version(
            definition_id=definition.definition_id,
            namespace_id="tenant-a",
            actor_ref="publisher-b",
            version_id=AgentDefinitionVersionId(uuid4()),
            version=1,
            created_at=CREATED,
        )
    failed = service.validate_draft(
        definition_id=definition.definition_id,
        namespace_id="tenant-a",
        actor_ref="publisher-b",
        evaluated_at=CREATED,
    )
    assert failed.status.value == "failed"
    with pytest.raises(DraftValidationFailedError):
        service.materialize_version(
            definition_id=definition.definition_id,
            namespace_id="tenant-a",
            actor_ref="publisher-b",
            version_id=AgentDefinitionVersionId(uuid4()),
            version=1,
            created_at=CREATED,
        )
    assert registry.get_version(definition.scope, AgentDefinitionVersionId(uuid4())) is None
    narrowed = service.update_draft(
        definition_id=definition.definition_id,
        namespace_id="tenant-a",
        actor_ref="publisher-b",
        expected_revision=0,
        updated_at=CREATED,
        model_policy_ref="policies/models/deepseek@v3",
    )
    assert narrowed.revision == 1
    passed = service.validate_draft(
        definition_id=definition.definition_id,
        namespace_id="tenant-a",
        actor_ref="publisher-b",
        evaluated_at=CREATED,
    )
    assert passed.status.value == "passed"
    version = service.materialize_version(
        definition_id=definition.definition_id,
        namespace_id="tenant-a",
        actor_ref="publisher-b",
        version_id=AgentDefinitionVersionId(uuid4()),
        version=1,
        created_at=CREATED,
    )
    assert version.version == 1
    assert version.model_policy_ref == "policies/models/deepseek@v3"
    fetched = registry.get_version(definition.scope, version.version_id)
    assert fetched == version
    replayed = service.materialize_version(
        definition_id=definition.definition_id,
        namespace_id="tenant-a",
        actor_ref="publisher-b",
        version_id=version.version_id,
        version=1,
        created_at=CREATED,
    )
    assert replayed == version


def test_namespace_isolation(dsn: str) -> None:
    registry = _registry(dsn)
    definition = registry.save_definition(_definition())
    other_scope = AgentDefinitionScope(
        authority_issuer=definition.authority_issuer,
        namespace_id="tenant-b",
        definition_id=definition.definition_id,
    )
    assert registry.get_definition(other_scope) is None


def test_eval_evidence_roundtrip(dsn: str) -> None:
    registry = _registry(dsn)
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    evidence = AgentDefinitionEvalEvidence(
        authority_issuer=definition.authority_issuer,
        namespace_id=definition.namespace_id,
        definition_id=definition.definition_id,
        version_id=version.version_id,
        evidence_id=uuid4(),
        definition_digest=version.definition_digest or "",
        passed=True,
        evaluator_actor="eval-bot@example",
        case_summary={"cases": 10, "passed": 10},
    )
    registry.record_eval_evidence(evidence)
    latest = registry.latest_eval_evidence(definition.scope, version.version_id)
    assert latest is not None
    assert latest.passed is True
    assert latest.case_summary == {"cases": 10, "passed": 10}
    assert latest.definition_digest == version.definition_digest
