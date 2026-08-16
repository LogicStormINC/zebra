"""Agent Definition draft, Version materialization and gated publication API.

Draft create/update, deterministic validation and immutable Version
materialization are always available; publish, deprecate and revoke are gated
on publication gate evidence and publisher authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agent_core.application.agent_definitions import (
    AgentDefinitionDraftService,
    AgentDefinitionDraftServiceError,
    DraftNotFoundError,
    DraftNotValidatedError,
    DraftValidationFailedError,
    MissingPublisherGrantError,
    PublisherGrantPort,
)
from agent_core.domain.agent_definitions import AgentDefinitionVersion
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
)
from agent_core.ports.agent_registry import AgentRegistryPort

from zebra_agent_api.responses import ApiResponse, bad_request, service_unavailable

if TYPE_CHECKING:
    from zebra_agent_api.routes import RouteRequest

_DRAFT_REFERENCE_FIELDS = (
    "model_policy_ref",
    "tool_profile_ref",
    "skill_snapshot_digest",
    "memory_policy_ref",
    "security_policy_ref",
    "evaluation_profile_ref",
    "runtime_profile_ref",
)
_DRAFT_FIELDS = ("name", "description", *_DRAFT_REFERENCE_FIELDS)


class ApiAgentDefinitionsMixin:
    """Draft lifecycle surface; fail closed without a composed Registry."""

    agent_registry: AgentRegistryPort | None = None
    publisher_grants: PublisherGrantPort | None = None

    def create_or_update_draft(
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
        service = self._draft_service()
        if isinstance(service, ApiResponse):
            return service
        expected_revision = payload.get("expected_revision")
        if expected_revision is not None and (
            not isinstance(expected_revision, int) or isinstance(expected_revision, bool)
        ):
            return bad_request("expected_revision must be a non-negative integer")
        try:
            if expected_revision is None:
                fields = _parse_draft_payload(payload, require_name=True)
                if isinstance(fields, ApiResponse):
                    return fields
                draft = service.create_draft(
                    definition_id=definition,
                    namespace_id=namespace_id,
                    actor_ref=actor_ref,
                    updated_at=_now(),
                    **fields,
                )
            else:
                fields = _parse_draft_payload(payload, require_name=False)
                if isinstance(fields, ApiResponse):
                    return fields
                draft = service.update_draft(
                    definition_id=definition,
                    namespace_id=namespace_id,
                    actor_ref=actor_ref,
                    expected_revision=expected_revision,
                    updated_at=_now(),
                    **fields,
                )
            return _draft_response(draft)
        except AgentDefinitionDraftServiceError as error:
            return _conflict(str(error))
        except MissingPublisherGrantError as error:
            return _forbidden(str(error))
        except ValueError as error:
            return bad_request(str(error))

    def validate_draft(
        self,
        definition_id: str,
        payload: dict[str, Any],
        *,
        host_context: HostContextEnvelope | None,
    ) -> ApiResponse:
        del payload
        definition = _parse_definition_id(definition_id)
        if isinstance(definition, ApiResponse):
            return definition
        authority = _require_host_context(host_context)
        if isinstance(authority, ApiResponse):
            return authority
        actor_ref, namespace_id = authority
        service = self._draft_service()
        if isinstance(service, ApiResponse):
            return service
        try:
            validation = service.validate_draft(
                definition_id=definition,
                namespace_id=namespace_id,
                actor_ref=actor_ref,
                evaluated_at=_now(),
            )
            return ApiResponse(
                status_code=200,
                body={
                    "definition_id": str(definition),
                    "draft_revision": validation.draft_revision,
                    "status": validation.status.value,
                    "issues": [issue.model_dump() for issue in validation.issues],
                },
            )
        except DraftNotFoundError as error:
            return _not_found(str(error))
        except MissingPublisherGrantError as error:
            return _forbidden(str(error))

    def materialize_version(
        self,
        definition_id: str,
        payload: dict[str, Any],
        *,
        host_context: HostContextEnvelope | None,
    ) -> ApiResponse:
        version_id = payload.get("version_id")
        version = payload.get("version")
        if not isinstance(version_id, str):
            return bad_request("version_id must be a UUID string")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            return bad_request("version must be a positive integer")
        definition = _parse_definition_id(definition_id)
        if isinstance(definition, ApiResponse):
            return definition
        authority = _require_host_context(host_context)
        if isinstance(authority, ApiResponse):
            return authority
        actor_ref, namespace_id = authority
        service = self._draft_service()
        if isinstance(service, ApiResponse):
            return service
        try:
            materialized = service.materialize_version(
                definition_id=definition,
                namespace_id=namespace_id,
                actor_ref=actor_ref,
                version_id=AgentDefinitionVersionId(UUID(version_id)),
                version=version,
                created_at=_now(),
            )
            return ApiResponse(status_code=201, body=_version_body(materialized))
        except DraftNotValidatedError as error:
            return bad_request(str(error))
        except DraftValidationFailedError as error:
            return bad_request(str(error))
        except DraftNotFoundError as error:
            return _not_found(str(error))
        except AgentDefinitionDraftServiceError as error:
            return _conflict(str(error))
        except MissingPublisherGrantError as error:
            return _forbidden(str(error))
        except ValueError as error:
            return bad_request(str(error))

    def _draft_service(
        self,
    ) -> AgentDefinitionDraftService | ApiResponse:
        if self.agent_registry is None or self.publisher_grants is None:
            return service_unavailable(
                status="registry_unavailable",
                reason="the cloud Agent Definition Registry is not composed",
            )
        return AgentDefinitionDraftService(self.agent_registry, self.publisher_grants)


def handle_agent_definition_route(
    app: Any,
    request: RouteRequest,
) -> ApiResponse | None:
    """Dispatch ``/agent-definitions/...`` POST routes; None means no match."""
    if request.method.upper() != "POST" or not request.path.startswith("/agent-definitions/"):
        return None
    segments = tuple(
        segment
        for segment in request.path.removeprefix("/agent-definitions/").split("/")
        if segment
    )
    if len(segments) < 2:
        return None
    definition_id = segments[0]
    body = request.body or {}
    if segments[1:] == ("draft",):
        return _as_response(
            app.create_or_update_draft(
                definition_id,
                body,
                host_context=request.host_context,
            )
        )
    if segments[1:] == ("draft", "validate"):
        return _as_response(
            app.validate_draft(
                definition_id,
                body,
                host_context=request.host_context,
            )
        )
    if segments[1:] == ("versions",):
        return _as_response(
            app.materialize_version(
                definition_id,
                body,
                host_context=request.host_context,
            )
        )
    if segments[1:] == ("release",):
        return _as_response(
            app.publish_release(
                definition_id,
                body,
                host_context=request.host_context,
            )
        )
    if segments[1:] == ("release", "deprecate"):
        return _as_response(
            app.deprecate_release(
                definition_id,
                body,
                host_context=request.host_context,
            )
        )
    if segments[1:] == ("release", "revoke"):
        return _as_response(
            app.revoke_release(
                definition_id,
                body,
                host_context=request.host_context,
            )
        )
    return None


def _as_response(value: Any) -> ApiResponse | None:
    if value is None or isinstance(value, ApiResponse):
        return value
    raise TypeError("agent definition route returned a non-response")


def _parse_draft_payload(
    payload: dict[str, Any],
    *,
    require_name: bool,
) -> dict[str, str] | ApiResponse:
    unknown = set(payload) - set(_DRAFT_FIELDS) - {"expected_revision"}
    if unknown:
        return bad_request(f"unknown draft fields: {sorted(unknown)}")
    fields: dict[str, str] = {}
    for field in _DRAFT_FIELDS:
        if field in payload:
            value = payload[field]
            if not isinstance(value, str):
                return bad_request(f"{field} must be a string")
            fields[field] = value
    if require_name and "name" not in fields:
        return bad_request("name is required")
    return fields


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


def _draft_response(draft: Any) -> ApiResponse:
    return ApiResponse(
        status_code=200,
        body={
            "definition_id": str(draft.definition_id),
            "namespace_id": draft.namespace_id,
            "name": draft.name,
            "description": draft.description,
            "revision": draft.revision,
            "updated_at": draft.updated_at.isoformat(),
        },
    )


def _version_body(version: AgentDefinitionVersion) -> dict[str, object]:
    return {
        "definition_id": str(version.definition_id),
        "version_id": str(version.version_id),
        "version": version.version,
        "schema_version": version.schema_version,
        "model_policy_ref": version.model_policy_ref,
        "tool_profile_ref": version.tool_profile_ref,
        "skill_snapshot_digest": version.skill_snapshot_digest,
        "memory_policy_ref": version.memory_policy_ref,
        "security_policy_ref": version.security_policy_ref,
        "evaluation_profile_ref": version.evaluation_profile_ref,
        "runtime_profile_ref": version.runtime_profile_ref,
        "definition_digest": version.definition_digest,
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(reason: str) -> ApiResponse:
    return ApiResponse(
        status_code=409,
        body={"status": "revision_conflict", "reason": reason},
    )


def _forbidden(reason: str) -> ApiResponse:
    return ApiResponse(status_code=403, body={"status": "forbidden", "reason": reason})


def _not_found(reason: str) -> ApiResponse:
    return ApiResponse(status_code=404, body={"status": "not_found", "reason": reason})
