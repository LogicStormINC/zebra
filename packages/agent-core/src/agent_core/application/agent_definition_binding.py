"""Task-level Definition binding resolver (AGENT-DEF-BIND-01, ADR-016 §6/§8).

Production Task creation resolves the current effective Published Release into
an immutable snapshot. A bounded pre-publication Eval path exact-pins a
candidate Version without creating a Release; it requires evaluator authority,
an explicit non-production environment and never becomes the production default.
"""

from __future__ import annotations

from datetime import datetime

from agent_core.application.agent_definitions import PublisherGrantPort
from agent_core.domain.agent_definition_snapshots import (
    AgentDefinitionSnapshot,
    canonical_agent_definition_snapshot_digest,
)
from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.identifiers import AgentDefinitionVersionId
from agent_core.ports.agent_registry import AgentRegistryPort


class DefinitionBindingError(ValueError):
    """Raised when a Definition cannot be bound to a Task."""


class NoPublishedReleaseError(DefinitionBindingError):
    """Raised when no effective Published Release exists for the scope."""


class EvalBindingDeniedError(DefinitionBindingError):
    """Raised when an Eval binding is attempted without authority or isolation."""


class DefinitionBindingService:
    """Resolves one immutable Version into a Task-level snapshot."""

    def __init__(
        self,
        registry: AgentRegistryPort,
        publisher_grants: PublisherGrantPort,
    ) -> None:
        self._registry = registry
        self._publisher_grants = publisher_grants

    def resolve_production_snapshot(
        self,
        scope: AgentDefinitionScope,
        *,
        environment: str,
        resolved_at: datetime,
    ) -> AgentDefinitionSnapshot:
        release = self._registry.resolve_published(scope, environment=environment)
        if release is None:
            raise NoPublishedReleaseError(
                f"no effective Published Release for {scope.namespace_id!r} in"
                f" environment {environment!r}"
            )
        version = self._registry.get_version(scope, release.version_id)
        if version is None or (version.definition_digest or "") != release.definition_digest:
            raise DefinitionBindingError(
                "Published Release references a Version that is missing or"
                " digest-mismatched; failing closed"
            )
        return AgentDefinitionSnapshot.from_release(
            release=release,
            version=version,
            resolved_at=resolved_at,
        )

    def resolve_eval_snapshot(
        self,
        scope: AgentDefinitionScope,
        *,
        environment: str,
        version_id: AgentDefinitionVersionId,
        actor_ref: str,
        resolved_at: datetime,
    ) -> AgentDefinitionSnapshot:
        if environment == "production":
            raise EvalBindingDeniedError(
                "candidate Version binding cannot use the production environment"
            )
        ceiling = self._publisher_grants.ceiling_for(scope.namespace_id, actor_ref)
        if ceiling is None or ceiling.namespace_id != scope.namespace_id:
            raise EvalBindingDeniedError(
                f"actor {actor_ref!r} has no evaluator authority in"
                f" {scope.namespace_id!r}; failing closed"
            )
        version = self._registry.get_version(scope, version_id)
        if version is None:
            raise DefinitionBindingError(
                "candidate Version does not exist in this scope"
            )
        return AgentDefinitionSnapshot.from_version(
            version=version,
            resolved_at=resolved_at,
        )


def validate_recovered_snapshot(
    snapshot: AgentDefinitionSnapshot,
) -> None:
    """Recovery-side digest check; never reads Registry or mutable drafts.

    Parsing through the model already recomputed both canonical digests; this
    explicit check only guards against a snapshot whose self-digest is valid
    but whose definition digest was never verified against a Version. Callers
    that hold the bound Version must use ``version_digest_matches_snapshot``.
    """
    if canonical_agent_definition_snapshot_digest(snapshot) != snapshot.snapshot_digest:
        raise DefinitionBindingError("recovered Definition snapshot digest mismatch")
