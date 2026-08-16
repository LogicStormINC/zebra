"""Gated Definition publication service (AGENT-DEF-PUB-01, ADR-016 §8/§9).

Publish requires a passing AgentVersionPublicationGate for the exact Version
digest plus current publisher authority; deprecate/revoke append typed actor,
reason_class, enforcement_mode and effective_at. Immediate enforcement requires
security-revocation authority. Release history stays append-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from agent_core.application.agent_definitions import (
    MissingPublisherGrantError,
    PublisherGrantCeiling,
    PublisherGrantPort,
)
from agent_core.domain.agent_definitions import (
    AgentDefinitionScope,
    AgentRelease,
    AgentReleaseEnforcementMode,
    AgentReleaseStatus,
)
from agent_core.domain.identifiers import (
    AgentDefinitionVersionId,
    AgentReleaseId,
)
from agent_core.ports.agent_registry import AgentRegistryPort


class AgentPublicationError(ValueError):
    """Raised when a gated publication mutation is refused."""


class PublicationGateNotPassedError(AgentPublicationError):
    """Raised when the exact Version digest lacks a passing gate."""


class SecurityRevocationDeniedError(AgentPublicationError):
    """Raised when immediate enforcement lacks security-revocation authority."""


@dataclass(frozen=True)
class PublicationGateEvidence:
    """Core-shaped gate evidence; the observability gate produces it."""

    version_id: AgentDefinitionVersionId
    definition_digest: str
    passed: bool
    policy_version: str


class AgentDefinitionPublicationService:
    """Append-only publish/deprecate/revoke with typed evidence."""

    def __init__(
        self,
        registry: AgentRegistryPort,
        publisher_grants: PublisherGrantPort,
        *,
        security_revocation_actors: frozenset[str] = frozenset(),
    ) -> None:
        self._registry = registry
        self._publisher_grants = publisher_grants
        self._security_revocation_actors = security_revocation_actors

    def publish(
        self,
        scope: AgentDefinitionScope,
        *,
        version_id: AgentDefinitionVersionId,
        environment: str,
        actor_ref: str,
        gate: PublicationGateEvidence,
        effective_at: datetime,
    ) -> AgentRelease:
        self._require_grant(scope, actor_ref)
        version = self._registry.get_version(scope, version_id)
        if version is None:
            raise AgentPublicationError("cannot publish an unknown Version")
        if gate.version_id != version_id:
            raise PublicationGateNotPassedError(
                "publication gate evidence targets a different Version"
            )
        if gate.definition_digest != (version.definition_digest or ""):
            raise PublicationGateNotPassedError(
                "publication gate evidence does not pin the exact Version digest"
            )
        if not gate.passed:
            raise PublicationGateNotPassedError(
                "publication requires a passing AgentVersionPublicationGate for the"
                " exact Version digest"
            )
        return self._registry.append_release(
            AgentRelease.from_version(
                version,
                release_id=AgentReleaseId(uuid4()),
                environment=environment,
                actor_ref=actor_ref,
                effective_at=effective_at,
            )
        )

    def deprecate(
        self,
        scope: AgentDefinitionScope,
        *,
        environment: str,
        actor_ref: str,
        reason_class: str,
        effective_at: datetime,
        enforcement_mode: AgentReleaseEnforcementMode = (
            AgentReleaseEnforcementMode.SAFE_BOUNDARY
        ),
    ) -> AgentRelease | None:
        self._require_grant(scope, actor_ref)
        current = self._registry.resolve_published(scope, environment=environment)
        if current is None:
            return None
        return self._registry.append_release(
            current.transition(
                AgentReleaseStatus.DEPRECATED,
                revision=current.revision + 1,
                actor_ref=actor_ref,
                reason_class=reason_class,
                enforcement_mode=enforcement_mode,
                effective_at=effective_at,
            )
        )

    def revoke(
        self,
        scope: AgentDefinitionScope,
        *,
        environment: str,
        actor_ref: str,
        reason_class: str,
        effective_at: datetime,
        enforcement_mode: AgentReleaseEnforcementMode,
    ) -> AgentRelease | None:
        self._require_grant(scope, actor_ref)
        if (
            enforcement_mode is AgentReleaseEnforcementMode.IMMEDIATE
            and actor_ref not in self._security_revocation_actors
        ):
            raise SecurityRevocationDeniedError(
                "immediate enforcement requires security-revocation authority"
            )
        current = self._registry.resolve_published(scope, environment=environment)
        if current is None:
            return None
        return self._registry.append_release(
            current.transition(
                AgentReleaseStatus.REVOKED,
                revision=current.revision + 1,
                actor_ref=actor_ref,
                reason_class=reason_class,
                enforcement_mode=enforcement_mode,
                effective_at=effective_at,
            )
        )

    def _require_grant(
        self,
        scope: AgentDefinitionScope,
        actor_ref: str,
    ) -> PublisherGrantCeiling:
        ceiling = self._publisher_grants.ceiling_for(scope.namespace_id, actor_ref)
        if ceiling is None or ceiling.namespace_id != scope.namespace_id:
            raise MissingPublisherGrantError(
                f"actor {actor_ref!r} has no publisher authority in"
                f" {scope.namespace_id!r}; failing closed"
            )
        if ceiling.authority_issuer != scope.authority_issuer:
            raise MissingPublisherGrantError(
                "publisher grant issuer does not match the Definition scope"
            )
        return ceiling
