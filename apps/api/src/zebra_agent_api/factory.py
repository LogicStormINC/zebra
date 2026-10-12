from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from agent_core.application.agent_definitions import PublisherGrantPort
from agent_core.ports import EffectStateReadPort, LiveEventFanoutPort
from agent_core.ports.agent_registry import AgentRegistryPort
from agent_core.ports.task_schedules import TaskScheduleFiringStorePort, TaskScheduleStorePort
from agent_integrations import GitHubPullRequestTransport, RedisCommittedEventPublisher
from agent_integrations.redis_live_fanout_async import AsyncRedisNotifications
from agent_security import CredentialBroker
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    PostgresControlPlaneStores,
    cloud_composition_from_environment,
    compose_control_plane_stores,
    with_committed_event_publisher,
)
from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.usage_evidence import PostgresUsageEvidenceStore
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_api.api_workspace_mixin import WorkspaceControlStorePort
from zebra_agent_api.credential_broker import build_default_credential_broker
from zebra_agent_api.session_context_namespace import resolve_context_namespace
from zebra_agent_api.stream_v2_authority import V2ReadAuthority
from zebra_agent_api.stream_v2_reader import StreamV2Reader
from zebra_agent_api.usage_api import UsageEvidenceReader

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi


def create_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    stores: ControlPlaneStores | None = None,
    cloud_composition: CloudCompositionSettings | None = None,
    cloud_control: PostgresDirectControl | None = None,
    command_outcome: PostgresCommandOutcomeReader | None = None,
    administrative_context_namespace: str | None = None,
    context_administrative_namespace: str | None = None,
    credential_broker: CredentialBroker | None = None,
    credential_env: Mapping[str, str] | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
    effect_state: EffectStateReadPort | None = None,
    workspace_control_store: WorkspaceControlStorePort | None = None,
    agent_registry: AgentRegistryPort | None = None,
    publisher_grants: PublisherGrantPort | None = None,
    publication_security_revocation_actors: frozenset[str] = frozenset(),
    task_schedule_store: TaskScheduleStorePort | None = None,
    task_schedule_firing_store: TaskScheduleFiringStorePort | None = None,
    usage_evidence: UsageEvidenceReader | None = None,
) -> ZebraAgentApi:
    from zebra_agent_api.app import ZebraAgentApi

    active_settings = settings or load_settings()
    if (
        active_settings.deployment == "cloud"
        and active_settings.stream.new_admission_enabled
        and (
            active_settings.stream.cursor_signing_key is None
            or active_settings.live_events.redis_url is None
        )
    ):
        raise ValueError("new v2 admission requires shared cursor key and Redis reader composition")
    active_database_path = Path(database_path or active_settings.database_url)
    active_stores = stores
    live_event_fanout: LiveEventFanoutPort | None = None
    composed_stores = None
    notifications = None
    stream_v2_reader = None
    if active_stores is None and active_settings.storage_authority == "postgresql":
        cloud_composition = cloud_composition or cloud_composition_from_environment()
        composed_stores = compose_control_plane_stores(
            profile=active_settings.profile,
            storage_authority=active_settings.storage_authority,
            database_path=active_settings.database_url,
            cloud=cloud_composition,
        )
        active_stores = composed_stores
        command_outcome = command_outcome or PostgresCommandOutcomeReader(
            cloud_composition.dsn, deployment_namespace=cloud_composition.deployment_namespace
        )
    if cloud_control is None and isinstance(active_stores, PostgresControlPlaneStores):
        cloud_control = PostgresDirectControl(
            cloud_composition.dsn if cloud_composition else active_settings.database_url,
            deployment_namespace=active_stores.deployment_namespace,
            task_io_connections=active_stores.task_io_connections,
        )
    if command_outcome is not None and (
        getattr(active_stores, "deployment_namespace", None) != command_outcome.deployment_namespace
    ):
        raise ValueError("command outcome composition does not match stores")
    if (
        usage_evidence is None
        and active_settings.deployment == "cloud"
        and active_settings.storage_authority == "postgresql"
    ):
        namespace = getattr(active_stores, "deployment_namespace", None)
        if isinstance(namespace, str) and namespace.strip():
            usage_evidence = PostgresUsageEvidenceStore(
                cloud_composition.dsn if cloud_composition else active_settings.database_url,
                deployment_namespace=namespace,
            )
    if usage_evidence is not None and (
        getattr(active_stores, "deployment_namespace", None) != usage_evidence.deployment_namespace
    ):
        raise ValueError("usage evidence composition does not match stores")
    if (
        cloud_control is not None
        and getattr(active_stores, "deployment_namespace", None)
        != cloud_control.deployment_namespace
    ):
        raise ValueError("cloud direct control composition does not match stores")
    if effect_state is None and composed_stores is not None:
        effect_state = composed_stores.effects
    if active_stores is not None and active_settings.live_events.redis_url is not None:
        namespace = getattr(active_stores, "deployment_namespace", None)
        if namespace is None and active_settings.deployment == "local":
            namespace = "local"
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("live Redis publishing requires deployment_namespace")
        notifications = AsyncRedisNotifications(
            active_settings.live_events.redis_url,
            key_prefix=active_settings.live_events.key_prefix,
        )
        if active_settings.stream.cursor_signing_key is not None and namespace != "local":
            stream_v2_reader = StreamV2Reader(
                V2ReadAuthority(
                    active_stores,
                    dsn=cloud_composition.dsn
                    if cloud_composition
                    else active_settings.database_url,
                    namespace=namespace,
                ),
                url=active_settings.live_events.redis_url,
                key=active_settings.stream.cursor_signing_key,
                live_prefix=active_settings.live_events.key_prefix,
            )
        publisher = RedisCommittedEventPublisher.from_url(
            active_settings.live_events.redis_url,
            deployment_namespace=namespace,
            max_stream_length=active_settings.live_events.stream_max_length,
            key_prefix=active_settings.live_events.key_prefix,
        )
        publisher_fanout = getattr(publisher, "fanout", None)
        if publisher_fanout is not None:
            live_event_fanout = cast(LiveEventFanoutPort, publisher_fanout)
        active_stores = with_committed_event_publisher(
            active_stores,
            publisher,
        )
    active_broker = credential_broker
    if active_broker is None:
        active_broker = build_default_credential_broker(active_settings.scm, env=credential_env)
    if workspace_control_store is None and composed_stores is not None:
        from agent_storage import PostgresWorkspaceControlStore

        namespace = getattr(composed_stores, "deployment_namespace", None)
        if isinstance(namespace, str) and namespace.strip():
            workspace_control_store = PostgresWorkspaceControlStore(
                active_settings.database_url,
                deployment_namespace=namespace,
            )
    if agent_registry is None and composed_stores is not None:
        from agent_core.application.agent_definitions import (
            StaticPublisherGrantResolver,
        )
        from agent_storage import PostgresAgentRegistry

        namespace = getattr(composed_stores, "deployment_namespace", None)
        if isinstance(namespace, str) and namespace.strip():
            agent_registry = PostgresAgentRegistry(
                active_settings.database_url,
                deployment_namespace=namespace,
            )
            publisher_grants = publisher_grants or StaticPublisherGrantResolver({})
    if (
        active_settings.deployment == "cloud"
        and active_settings.storage_authority == "postgresql"
        and (task_schedule_store is None or task_schedule_firing_store is None)
    ):
        from agent_storage import PostgresTaskScheduleFiringStore, PostgresTaskScheduleStore

        namespace = getattr(active_stores, "deployment_namespace", None)
        if isinstance(namespace, str) and namespace.strip():
            task_schedule_store = task_schedule_store or PostgresTaskScheduleStore(
                active_settings.database_url, deployment_namespace=namespace
            )
            task_schedule_firing_store = (
                task_schedule_firing_store
                or PostgresTaskScheduleFiringStore(
                    active_settings.database_url, deployment_namespace=namespace
                )
            )
    client_platform = None
    if (
        active_settings.client_integration_enabled
        and active_settings.storage_authority == "postgresql"
    ):
        from zebra_agent_api.platform_composition import (
            compose_api_platform_control_plane,
        )

        namespace = getattr(composed_stores, "deployment_namespace", None)
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("client integration requires deployment_namespace")
        client_platform = compose_api_platform_control_plane(
            active_settings.database_url,
            deployment_namespace=namespace,
            client_integration_enabled=True,
        )
    from zebra_agent_api.platform_operator_auth import (
        StaticTokenPlatformOperatorAuthorizer,
    )

    operator_authorizer = StaticTokenPlatformOperatorAuthorizer(
        active_settings.platform_operator_token,
        strict=active_settings.deployment != "local",
    )
    from zebra_agent_api.coverage_http_admission import compose_coverage_http_admission

    coverage_http_admission = compose_coverage_http_admission(active_settings, active_stores)
    return ZebraAgentApi(
        database_path=active_database_path,
        settings=active_settings,
        _stores=active_stores,
        workspace_control_store=workspace_control_store,
        live_event_fanout=live_event_fanout,
        stream_notifications=notifications,
        stream_v2_reader=stream_v2_reader,
        administrative_context_namespace=resolve_context_namespace(
            administrative_context_namespace, context_administrative_namespace
        ),
        credential_broker=active_broker,
        github_transport=github_transport,
        effect_state=effect_state,
        agent_registry=agent_registry,
        publisher_grants=publisher_grants,
        publication_security_revocation_actors=publication_security_revocation_actors,
        client_platform=client_platform,
        platform_operator_authorizer=operator_authorizer,
        cloud_control=cloud_control,
        command_outcome=command_outcome,
        task_schedule_store=task_schedule_store,
        task_schedule_firing_store=task_schedule_firing_store,
        usage_evidence=usage_evidence,
        coverage_http_admission=coverage_http_admission,
    )
