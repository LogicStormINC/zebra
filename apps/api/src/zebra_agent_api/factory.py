from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from agent_core.application.agent_definitions import PublisherGrantPort
from agent_core.ports import EffectStateReadPort, LiveEventFanoutPort
from agent_core.ports.agent_registry import AgentRegistryPort
from agent_integrations import GitHubPullRequestTransport, RedisCommittedEventPublisher
from agent_security import CredentialBroker
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    compose_control_plane_stores,
    with_committed_event_publisher,
)
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_api.api_workspace_mixin import WorkspaceControlStorePort
from zebra_agent_api.credential_broker import build_default_credential_broker
from zebra_agent_api.session_context_namespace import resolve_context_namespace

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi


def create_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    stores: ControlPlaneStores | None = None,
    cloud_composition: CloudCompositionSettings | None = None,
    administrative_context_namespace: str | None = None,
    context_administrative_namespace: str | None = None,
    credential_broker: CredentialBroker | None = None,
    credential_env: Mapping[str, str] | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
    effect_state: EffectStateReadPort | None = None,
    workspace_control_store: WorkspaceControlStorePort | None = None,
    agent_registry: AgentRegistryPort | None = None,
    publisher_grants: PublisherGrantPort | None = None,
) -> ZebraAgentApi:
    from zebra_agent_api.app import ZebraAgentApi

    active_settings = settings or load_settings()
    active_database_path = Path(database_path or active_settings.database_url)
    active_stores = stores
    live_event_fanout: LiveEventFanoutPort | None = None
    composed_stores = None
    if active_stores is None and active_settings.storage_authority == "postgresql":
        composed_stores = compose_control_plane_stores(
            profile=active_settings.profile,
            storage_authority=active_settings.storage_authority,
            database_path=active_settings.database_url,
            cloud=cloud_composition,
        )
        active_stores = composed_stores
    if effect_state is None and composed_stores is not None:
        effect_state = composed_stores.effects
    if active_stores is not None and active_settings.live_events.redis_url is not None:
        namespace = getattr(active_stores, "deployment_namespace", None)
        if namespace is None and active_settings.deployment == "local":
            namespace = "local"
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("live Redis publishing requires deployment_namespace")
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
    return ZebraAgentApi(
        database_path=active_database_path,
        settings=active_settings,
        _stores=active_stores,
        workspace_control_store=workspace_control_store,
        live_event_fanout=live_event_fanout,
        administrative_context_namespace=resolve_context_namespace(
            administrative_context_namespace, context_administrative_namespace
        ),
        credential_broker=active_broker,
        github_transport=github_transport,
        effect_state=effect_state,
        agent_registry=agent_registry,
        publisher_grants=publisher_grants,
    )
