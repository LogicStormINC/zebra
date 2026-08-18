"""Gated publication API surface (AGENT-DEF-PUB-01).

Publish requires passing gate evidence pinned to the exact Version digest plus
publisher authority; deprecate/revoke append typed actor, reason_class,
enforcement_mode and effective_at. Immediate enforcement requires
security-revocation authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.application.agent_definitions import (
    MissingPublisherGrantError,
    PublisherGrantPort,
)
from agent_core.application.agent_publication import (
    AgentDefinitionPublicationService,
    AgentPublicationError,
    PublicationGateEvidence,
    PublicationGateNotPassedError,
    SecurityRevocationDeniedError,
)
from agent_core.domain.agent_definitions import (
    AgentDefinitionScope,
    AgentReleaseEnforcementMode,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
)
from agent_core.ports.agent_registry import AgentRegistryPort

from zebra_agent_api.responses import ApiResponse, bad_request, service_unavailable


class ApiAgentReleaseMixin:
    """Release mutation surface; always gated and namespace-bound."""

    agent_registry: AgentRegistryPort | None = None
    publisher_grants: PublisherGrantPort | None = None
    publication_security_revocation_actors: frozenset[str] = frozenset()

    def publish_release(
        self,
        definition_id: str,
        payload: dict[str, Any],
        *,
        host_context: HostContextEnvelope | None,
    ) -> ApiResponse:
        definition = _parse_definition_id(definition_id)
        if isinstance(definition, ApiResponse):
            return definition
        authority = _require_host_context(host_context)
        if isinstance(authority, ApiResponse):
            return authority
        actor_ref, namespace_id = authority
        version_id = payload.get("version_id")
        environment = payload.get("environment")
        raw_gate = payload.get("gate")
        if not isinstance(version_id, str):
            return bad_request("version_id must be a UUID string")
        if not isinstance(environment, str) or not environment.strip():
            return bad_request("environment must be a non-blank string")
        if not isinstance(raw_gate, dict):
            return bad_request("gate evidence is required for publication")
        gate = _parse_gate_evidence(raw_gate, version_id)
        if isinstance(gate, ApiResponse):
            return gate
        service = self._publication_service()
        if isinstance(service, ApiResponse):
            return service
        try:
            release = service.publish(
                _scope(self, definition, namespace_id, host_context),
                version_id=AgentDefinitionVersionId(UUID(version_id)),
                environment=environment.strip(),
                actor_ref=actor_ref,
                gate=gate,
                effective_at=_now(),
            )
            return ApiResponse(
                status_code=201,
                body={
                    "release_id": str(release.release_id),
                    "environment": release.environment,
                    "status": release.status.value,
                    "revision": release.revision,
                    "version_id": str(release.version_id),
                },
            )
        except (PublicationGateNotPassedError, AgentPublicationError) as error:
            return _conflict(str(error))
        except MissingPublisherGrantError as error:
            return _forbidden(str(error))

    def deprecate_release(
        self,
        definition_id: str,
        payload: dict[str, Any],
        *,
        host_context: HostContextEnvelope | None,
    ) -> ApiResponse:
        return self._transition_release(
            definition_id,
            payload,
            host_context=host_context,
            revoke=False,
        )

    def revoke_release(
        self,
        definition_id: str,
        payload: dict[str, Any],
        *,
        host_context: HostContextEnvelope | None,
    ) -> ApiResponse:
        return self._transition_release(
            definition_id,
            payload,
            host_context=host_context,
            revoke=True,
        )

    def _transition_release(
        self,
        definition_id: str,
        payload: dict[str, Any],
        *,
        host_context: HostContextEnvelope | None,
        revoke: bool,
    ) -> ApiResponse:
        definition = _parse_definition_id(definition_id)
        if isinstance(definition, ApiResponse):
            return definition
        authority = _require_host_context(host_context)
        if isinstance(authority, ApiResponse):
            return authority
        actor_ref, namespace_id = authority
        environment = payload.get("environment")
        reason_class = payload.get("reason_class")
        if not isinstance(environment, str) or not environment.strip():
            return bad_request("environment must be a non-blank string")
        if not isinstance(reason_class, str) or not reason_class.strip():
            return bad_request("reason_class must be a non-blank string")
        enforcement_mode = _parse_enforcement_mode(payload.get("enforcement_mode"))
        if isinstance(enforcement_mode, ApiResponse):
            return enforcement_mode
        service = self._publication_service()
        if isinstance(service, ApiResponse):
            return service
        try:
            transition = (
                service.revoke if revoke else service.deprecate
            )(
                _scope(self, definition, namespace_id, host_context),
                environment=environment.strip(),
                actor_ref=actor_ref,
                reason_class=reason_class.strip(),
                effective_at=_now(),
                enforcement_mode=enforcement_mode,
            )
            if transition is None:
                return _not_found("no effective Published Release exists")
            return ApiResponse(
                status_code=200,
                body={
                    "release_id": str(transition.release_id),
                    "environment": transition.environment,
                    "status": transition.status.value,
                    "revision": transition.revision,
                    "reason_class": transition.reason_class,
                    "enforcement_mode": transition.enforcement_mode.value,
                },
            )
        except SecurityRevocationDeniedError as error:
            return _forbidden(str(error))
        except AgentPublicationError as error:
            return _conflict(str(error))
        except MissingPublisherGrantError as error:
            return _forbidden(str(error))

    def _publication_service(
        self,
    ) -> AgentDefinitionPublicationService | ApiResponse:
        if self.agent_registry is None or self.publisher_grants is None:
            return service_unavailable(
                status="registry_unavailable",
                reason="the cloud Agent Definition Registry is not composed",
            )
        return AgentDefinitionPublicationService(
            self.agent_registry,
            self.publisher_grants,
            security_revocation_actors=self.publication_security_revocation_actors,
        )


def _scope(
    mixin: ApiAgentReleaseMixin,
    definition: AgentDefinitionId,
    namespace_id: str,
    host_context: HostContextEnvelope | None,
) -> AgentDefinitionScope:
    if host_context is None or mixin.publisher_grants is None:
        raise MissingPublisherGrantError("host authority context is required")
    ceiling = mixin.publisher_grants.ceiling_for(
        namespace_id,
        host_context.host_app_id,
    )
    if ceiling is None or ceiling.namespace_id != namespace_id:
        raise MissingPublisherGrantError(
            "host app has no publisher authority in this namespace"
        )
    return AgentDefinitionScope(
        authority_issuer=ceiling.authority_issuer,
        namespace_id=namespace_id,
        definition_id=definition,
    )


def _parse_definition_id(definition_id: str) -> AgentDefinitionId | ApiResponse:
    try:
        return AgentDefinitionId(UUID(definition_id))
    except (ValueError, AttributeError):
        return bad_request("definition_id must be a UUID string")


def _require_host_context(
    host_context: HostContextEnvelope | None,
) -> tuple[str, str] | ApiResponse:
    if host_context is None:
        return ApiResponse(
            status_code=403,
            body={
                "status": "forbidden",
                "reason": "host authority context is required",
            },
        )
    return host_context.host_app_id, host_context.namespace_id


def _parse_gate_evidence(
    raw: dict[str, object],
    version_id: str,
) -> PublicationGateEvidence | ApiResponse:
    passed = raw.get("passed")
    policy_version = raw.get("policy_version")
    definition_digest = raw.get("definition_digest")
    if not isinstance(passed, bool):
        return bad_request("gate.passed must be a boolean")
    if not isinstance(policy_version, str) or not policy_version.strip():
        return bad_request("gate.policy_version must be a non-blank string")
    if not isinstance(definition_digest, str) or not definition_digest.strip():
        return bad_request("gate.definition_digest must be a non-blank string")
    try:
        return PublicationGateEvidence(
            version_id=AgentDefinitionVersionId(UUID(version_id)),
            definition_digest=definition_digest.strip().lower(),
            passed=passed,
            policy_version=policy_version.strip(),
        )
    except (ValueError, AttributeError):
        return bad_request("gate evidence version_id must be a UUID string")


def _parse_enforcement_mode(
    value: object,
) -> AgentReleaseEnforcementMode | ApiResponse:
    if value is None:
        return AgentReleaseEnforcementMode.SAFE_BOUNDARY
    if not isinstance(value, str):
        return bad_request("enforcement_mode must be a string")
    try:
        return AgentReleaseEnforcementMode(value)
    except ValueError:
        return bad_request("enforcement_mode must be safe-boundary or immediate")


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(reason: str) -> ApiResponse:
    return ApiResponse(
        status_code=409,
        body={"status": "publication_conflict", "reason": reason},
    )


def _forbidden(reason: str) -> ApiResponse:
    return ApiResponse(status_code=403, body={"status": "forbidden", "reason": reason})


def _not_found(reason: str) -> ApiResponse:
    return ApiResponse(status_code=404, body={"status": "not_found", "reason": reason})
