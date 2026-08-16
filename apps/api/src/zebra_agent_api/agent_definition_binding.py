"""Production Definition binding for session creation (AGENT-DEF-BIND-01)."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_core.application.agent_definition_binding import (
    DefinitionBindingError,
    DefinitionBindingService,
)
from agent_core.application.agent_definitions import PublisherGrantPort
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.ports.agent_registry import AgentRegistryPort

from zebra_agent_api.responses import ApiResponse, conflict, service_unavailable
from zebra_agent_api.session_payloads import CreateSessionPayload


def resolve_definition_binding(
    registry: AgentRegistryPort | None,
    publisher_grants: PublisherGrantPort | None,
    parsed: CreateSessionPayload,
    *,
    host_context: HostContextEnvelope | None,
) -> AgentDefinitionSnapshot | ApiResponse | None:
    """Resolve the production snapshot for a requested definition; None unbound."""
    definition_id = parsed.get("definition_id")
    if definition_id is None:
        return None
    if registry is None or publisher_grants is None:
        return service_unavailable(
            status="registry_unavailable",
            reason="definition binding requires the cloud Agent Definition Registry",
        )
    if host_context is None:
        return ApiResponse(
            status_code=403,
            body={
                "status": "forbidden",
                "reason": "host authority context is required for definition binding",
            },
        )
    ceiling = publisher_grants.ceiling_for(
        host_context.namespace_id,
        host_context.host_app_id,
    )
    if ceiling is None or ceiling.namespace_id != host_context.namespace_id:
        return ApiResponse(
            status_code=403,
            body={
                "status": "forbidden",
                "reason": "host app has no publisher authority in this namespace",
            },
        )
    binding = DefinitionBindingService(registry, publisher_grants)
    scope = AgentDefinitionScope(
        authority_issuer=ceiling.authority_issuer,
        namespace_id=host_context.namespace_id,
        definition_id=definition_id,
    )
    environment = str(parsed.get("definition_environment") or "production")
    try:
        return binding.resolve_production_snapshot(
            scope,
            environment=environment,
            resolved_at=datetime.now(UTC),
        )
    except DefinitionBindingError as error:
        return conflict(
            session_id="",
            status="definition_binding_failed",
            reason=str(error),
        )
