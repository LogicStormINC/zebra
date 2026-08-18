"""Draft validation and immutable Version materialization (AGENT-DEF-DRAFT-01).

This service is the only mutation path for Definition drafts: every mutation
checks the external publisher grant (fail closed when absent), enforces
optimistic revision CAS and idempotency, and never exposes publish, deprecate
or revoke. Validation failures become append-only evidence and never create a
Version; Version-level Eval gates Release later, not Version materialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from agent_core.domain.agent_definition_drafts import (
    AgentDefinitionDraft,
    AgentDefinitionDraftValidation,
    AgentDraftValidationIssue,
    AgentDraftValidationStatus,
)
from agent_core.domain.agent_definitions import (
    _REQUIRED_REFERENCE_FIELDS,
    AgentDefinition,
    AgentDefinitionScope,
    AgentDefinitionVersion,
)
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
)
from agent_core.ports.agent_registry import AgentRegistryPort


class PublisherGrantError(ValueError):
    """Raised when a mutation exceeds the publisher's authority ceiling."""


class MissingPublisherGrantError(PublisherGrantError):
    """Raised when no grant exists for the actor/namespace (fail closed)."""


class AgentDefinitionDraftServiceError(ValueError):
    """Raised for invalid draft state or stale materialization inputs."""


class DraftNotFoundError(AgentDefinitionDraftServiceError):
    """Raised when a mutation targets a Definition without a draft."""


class DraftNotValidatedError(AgentDefinitionDraftServiceError):
    """Raised when materialization cannot be backed by fresh validation."""


class DraftValidationFailedError(AgentDefinitionDraftServiceError):
    """Raised when materialization is attempted over failed validation."""


@dataclass(frozen=True)
class PublisherGrantCeiling:
    """The publisher authority upper bound for one actor/namespace."""

    authority_issuer: str
    namespace_id: str
    allowed_references: frozenset[str]

    def allows(self, reference: str) -> bool:
        return _reference_within_grant(reference, self.allowed_references)


class PublisherGrantPort(Protocol):
    """Resolves the external publisher authority ceiling; None fails closed."""

    def ceiling_for(
        self,
        namespace_id: str,
        actor_ref: str,
    ) -> PublisherGrantCeiling | None: ...


class StaticPublisherGrantResolver:
    """Deterministic config-driven grants keyed by ``{actor}@{namespace}``."""

    def __init__(self, grants: dict[str, PublisherGrantCeiling]) -> None:
        self._grants = dict(grants)

    def ceiling_for(
        self,
        namespace_id: str,
        actor_ref: str,
    ) -> PublisherGrantCeiling | None:
        return self._grants.get(f"{actor_ref}@{namespace_id}")


class AgentDefinitionDraftService:
    """Bounded draft lifecycle; no release mutation surface exists here."""

    def __init__(
        self,
        registry: AgentRegistryPort,
        publisher_grants: PublisherGrantPort,
    ) -> None:
        self._registry = registry
        self._publisher_grants = publisher_grants

    def create_draft(
        self,
        *,
        definition_id: AgentDefinitionId,
        namespace_id: str,
        actor_ref: str,
        name: str,
        description: str,
        model_policy_ref: str,
        tool_profile_ref: str,
        skill_snapshot_digest: str,
        memory_policy_ref: str,
        security_policy_ref: str,
        evaluation_profile_ref: str,
        runtime_profile_ref: str,
        updated_at: datetime,
    ) -> AgentDefinitionDraft:
        scope, ceiling = self._resolve_authority(namespace_id, definition_id, actor_ref)
        existing = self._registry.get_definition(scope)
        draft = AgentDefinitionDraft(
            definition_id=definition_id,
            authority_issuer=ceiling.authority_issuer,
            namespace_id=namespace_id,
            name=name,
            description=description,
            model_policy_ref=model_policy_ref,
            tool_profile_ref=tool_profile_ref,
            skill_snapshot_digest=skill_snapshot_digest,
            memory_policy_ref=memory_policy_ref,
            security_policy_ref=security_policy_ref,
            evaluation_profile_ref=evaluation_profile_ref,
            runtime_profile_ref=runtime_profile_ref,
            revision=0,
            updated_at=updated_at,
        )
        if existing is None:
            self._registry.save_definition(
                AgentDefinition(
                    definition_id=definition_id,
                    authority_issuer=ceiling.authority_issuer,
                    namespace_id=namespace_id,
                    name=name,
                    description=description,
                    revision=0,
                    created_at=updated_at,
                )
            )
        return self._registry.save_draft(draft)

    def update_draft(
        self,
        *,
        definition_id: AgentDefinitionId,
        namespace_id: str,
        actor_ref: str,
        expected_revision: int,
        updated_at: datetime,
        name: str | None = None,
        description: str | None = None,
        model_policy_ref: str | None = None,
        tool_profile_ref: str | None = None,
        skill_snapshot_digest: str | None = None,
        memory_policy_ref: str | None = None,
        security_policy_ref: str | None = None,
        evaluation_profile_ref: str | None = None,
        runtime_profile_ref: str | None = None,
    ) -> AgentDefinitionDraft:
        scope, _ = self._resolve_authority(namespace_id, definition_id, actor_ref)
        current = self._registry.get_draft(scope)
        if current is None:
            raise DraftNotFoundError("no draft exists for this Definition")
        if current.revision != expected_revision:
            raise AgentDefinitionDraftServiceError(
                f"draft revision conflict: durable revision is {current.revision}"
            )
        updates: dict[str, object] = {}
        for field, value in {
            "name": name,
            "description": description,
            "model_policy_ref": model_policy_ref,
            "tool_profile_ref": tool_profile_ref,
            "skill_snapshot_digest": skill_snapshot_digest,
            "memory_policy_ref": memory_policy_ref,
            "security_policy_ref": security_policy_ref,
            "evaluation_profile_ref": evaluation_profile_ref,
            "runtime_profile_ref": runtime_profile_ref,
        }.items():
            if value is not None:
                updates[field] = value
        if not updates:
            raise AgentDefinitionDraftServiceError("update_draft requires one field")
        updated = current.model_copy(update={**updates, "revision": current.revision + 1})
        return self._registry.save_draft(updated, expected_revision=expected_revision)

    def validate_draft(
        self,
        *,
        definition_id: AgentDefinitionId,
        namespace_id: str,
        actor_ref: str,
        evaluated_at: datetime,
    ) -> AgentDefinitionDraftValidation:
        scope, ceiling = self._resolve_authority(namespace_id, definition_id, actor_ref)
        draft = self._registry.get_draft(scope)
        if draft is None:
            raise DraftNotFoundError("no draft exists for this Definition")
        issues = validate_draft_content(draft, ceiling=ceiling)
        status = (
            AgentDraftValidationStatus.PASSED
            if not issues
            else AgentDraftValidationStatus.FAILED
        )
        validation = AgentDefinitionDraftValidation(
            definition_id=definition_id,
            authority_issuer=ceiling.authority_issuer,
            namespace_id=namespace_id,
            validation_id=uuid4(),
            draft_revision=draft.revision,
            status=status,
            issues=issues,
            evaluated_at=evaluated_at,
            evaluator_actor=actor_ref,
        )
        self._registry.append_draft_validation(validation)
        return validation

    def materialize_version(
        self,
        *,
        definition_id: AgentDefinitionId,
        namespace_id: str,
        actor_ref: str,
        version_id: AgentDefinitionVersionId,
        version: int,
        created_at: datetime,
    ) -> AgentDefinitionVersion:
        scope, ceiling = self._resolve_authority(namespace_id, definition_id, actor_ref)
        draft = self._registry.get_draft(scope)
        if draft is None:
            raise DraftNotFoundError("no draft exists for this Definition")
        definition = self._registry.get_definition(scope)
        if definition is None:
            raise AgentDefinitionDraftServiceError(
                "Definition metadata missing; cannot materialize a Version"
            )
        latest = self._registry.latest_draft_validation(scope)
        if latest is None or latest.draft_revision != draft.revision:
            raise DraftNotValidatedError(
                "validation is stale or absent; validate the current draft revision"
            )
        if latest.status is not AgentDraftValidationStatus.PASSED:
            raise DraftValidationFailedError(
                "latest draft validation failed; fix issues before materializing"
            )
        issues = validate_draft_content(draft, ceiling=ceiling)
        if issues:
            raise DraftValidationFailedError(
                "draft content is not within the publisher grant"
            )
        materialized = AgentDefinitionVersion.from_definition(
            definition,
            version_id=version_id,
            version=version,
            created_at=created_at,
            model_policy_ref=draft.model_policy_ref,
            tool_profile_ref=draft.tool_profile_ref,
            skill_snapshot_digest=draft.skill_snapshot_digest,
            memory_policy_ref=draft.memory_policy_ref,
            security_policy_ref=draft.security_policy_ref,
            evaluation_profile_ref=draft.evaluation_profile_ref,
            runtime_profile_ref=draft.runtime_profile_ref,
        )
        saved = self._registry.save_version(materialized)
        metadata_updated = definition.model_copy(
            update={"name": draft.name, "description": draft.description}
        )
        self._registry.save_definition(
            metadata_updated, expected_revision=definition.revision
        )
        return saved

    def _resolve_authority(
        self,
        namespace_id: str,
        definition_id: AgentDefinitionId,
        actor_ref: str,
    ) -> tuple[AgentDefinitionScope, PublisherGrantCeiling]:
        ceiling = self._publisher_grants.ceiling_for(namespace_id, actor_ref)
        if ceiling is None:
            raise MissingPublisherGrantError(
                f"no publisher grant for actor {actor_ref!r} in namespace"
                f" {namespace_id!r}; failing closed"
            )
        if ceiling.namespace_id != namespace_id:
            raise MissingPublisherGrantError(
                "publisher grant namespace mismatch; failing closed"
            )
        return (
            AgentDefinitionScope(
                authority_issuer=ceiling.authority_issuer,
                namespace_id=namespace_id,
                definition_id=definition_id,
            ),
            ceiling,
        )


def validate_draft_content(
    draft: AgentDefinitionDraft,
    *,
    ceiling: PublisherGrantCeiling,
) -> tuple[AgentDraftValidationIssue, ...]:
    """Deterministic static validation; never raises on content problems."""
    issues: list[AgentDraftValidationIssue] = []
    if ceiling.namespace_id != draft.namespace_id:
        issues.append(
            AgentDraftValidationIssue(
                code="cross-namespace",
                field="namespace_id",
                message="draft namespace is outside the publisher grant",
            )
        )
    for field in _REQUIRED_REFERENCE_FIELDS:
        reference = getattr(draft, field)
        if not ceiling.allows(reference):
            issues.append(
                AgentDraftValidationIssue(
                    code="reference-not-granted",
                    field=field,
                    message=(
                        f"reference {reference!r} is not within the publisher"
                        " grant ceiling"
                    ),
                )
            )
    return tuple(issues)


def _reference_within_grant(reference: str, granted: frozenset[str]) -> bool:
    declared_identity, declared_version = _split_reference(reference)
    if declared_identity is None or declared_version is None:
        return False
    for allowed in granted:
        identity, version = _split_reference(allowed)
        if identity is None or version is None:
            continue
        if identity != declared_identity:
            continue
        if _version_at_or_below(declared_version, version):
            return True
    return False


def _split_reference(reference: str) -> tuple[str | None, str | None]:
    if "@" not in reference:
        return None, None
    identity, version = reference.rsplit("@", 1)
    return identity, version


def _version_at_or_below(declared: str, ceiling: str) -> bool:
    """Dotted numeric compare; non-numeric versions fail closed (False)."""
    declared_parts = _numeric_parts(declared)
    ceiling_parts = _numeric_parts(ceiling)
    if declared_parts is None or ceiling_parts is None:
        return False
    return declared_parts <= ceiling_parts


def _numeric_parts(version: str) -> tuple[int, ...] | None:
    parts = version.removeprefix("v").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)
