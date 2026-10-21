"""Task consumption authority never creates a publisher ceiling for the business Host."""

from datetime import UTC, datetime

from agent_core.application.agent_definition_binding import (
    DefinitionBindingError,
    DefinitionBindingService,
)
from agent_core.application.agent_definitions import StaticPublisherGrantResolver
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.bundle_definition import BundleDefinitionSnapshot, BundleDefinitionVersion
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.ports.agent_registry import AgentRegistryPort
from agent_security.host_grant import VerifiedHostGrant
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.host_management import HostManagementStore
from agent_storage.postgres.publication import lock_definition
from agent_storage.postgres.work_unit import postgres_transaction_work_unit
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.publication_config import load_publication_approval
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_payloads import CreateSessionPayload


def resolve_consumer_binding(
    settings: object,
    registry: AgentRegistryPort | None,
    parsed: CreateSessionPayload,
    context: HostContextEnvelope | None,
    verified: object | None,
) -> AgentDefinitionSnapshot | ApiResponse:
    if not isinstance(settings, ZebraAgentSettings) or registry is None:
        return ApiResponse(503, {"status": "registry_unavailable"})
    if (
        not isinstance(verified, VerifiedHostGrant)
        or context is None
        or verified.context != context
    ):
        return ApiResponse(403, {"status": "forbidden"})
    try:
        approval = load_publication_approval(
            settings.publication_management_config, context.namespace_id
        )
        if (
            context.host_app_id not in approval.consumer_hosts
            or verified.authority_issuer != approval.scope.authority_issuer
            or str(parsed.get("definition_id")) != str(approval.definition_id)
            or (parsed.get("definition_environment") or "production") != approval.scope.environment
        ):
            return ApiResponse(403, {"status": "forbidden"})
        database = PostgresDatabase(
            settings.database_url, deployment_namespace=context.namespace_id
        )
        authority = HostManagementStore(
            settings.database_url, deployment_namespace=context.namespace_id
        )
        with authority.authorized(approval.trust) as connection:
            lock_definition(connection, approval.definition_scope.scope_key)
            with postgres_transaction_work_unit(database, connection):
                snapshot = DefinitionBindingService(
                    registry, StaticPublisherGrantResolver({})
                ).resolve_production_snapshot(
                    approval.definition_scope,
                    environment=approval.scope.environment,
                    resolved_at=datetime.now(UTC),
                )
            if not isinstance(snapshot, BundleDefinitionSnapshot):
                return ApiResponse(403, {"status": "forbidden"})
            version = snapshot.bound_version
            if (
                not isinstance(version, BundleDefinitionVersion)
                or version.runtime_assembly.bundle.manifest.scope != approval.scope
                or "runtime-bundle/"
                + version.runtime_assembly.bundle.bundle_digest.removeprefix("sha256:")
                + "@1"
                not in approval.references
            ):
                return ApiResponse(403, {"status": "forbidden"})
            if (
                load_publication_approval(
                    settings.publication_management_config, context.namespace_id
                )
                != approval
            ):
                raise PermissionError("STALE_CONSUMER_APPROVAL")
            authority._live(connection, approval.trust)
            return snapshot
    except DefinitionBindingError:
        return ApiResponse(409, {"status": "definition_binding_failed"})
    except PermissionError:
        return ApiResponse(403, {"status": "forbidden"})
    except (OSError, ValueError, TypeError):
        return ApiResponse(503, {"status": "registry_unavailable"})
