"""Compose durable replay with best-effort Redis live delivery."""

from collections.abc import Callable

from agent_core.ports import WorkerProjectionTransactionPort
from agent_core.ports.task_projection_checkpoints import ProjectionCheckpointHead
from agent_integrations import RedisCommittedEventPublisher
from agent_runtime.stream_hint_relay import StreamHintRelay
from agent_storage import (
    ControlPlaneStores,
    PostgresAgentTaskStore,
    PostgresControlPlaneStores,
    with_committed_event_publisher,
    with_worker_projection_publisher,
)
from zebra_agent_config import ZebraAgentSettings


def configure_live_event_delivery(
    stores: ControlPlaneStores | PostgresControlPlaneStores,
    transaction: WorkerProjectionTransactionPort | None,
    settings: ZebraAgentSettings,
) -> tuple[
    ControlPlaneStores | PostgresControlPlaneStores,
    WorkerProjectionTransactionPort | None,
]:
    if settings.live_events.redis_url is None or settings.deployment == "cloud":
        return stores, transaction
    namespace = getattr(stores, "deployment_namespace", None)
    if namespace is None and settings.deployment == "local":
        namespace = "local"
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("live Redis publishing requires deployment_namespace")
    publisher = RedisCommittedEventPublisher.from_url(
        settings.live_events.redis_url,
        deployment_namespace=namespace,
        max_stream_length=settings.live_events.stream_max_length,
        key_prefix=settings.live_events.key_prefix,
    )
    stores = with_committed_event_publisher(stores, publisher)
    if transaction is not None:
        transaction = with_worker_projection_publisher(transaction, publisher)
    return stores, transaction


def configure_stream_hint_relay(
    stores: ControlPlaneStores | PostgresControlPlaneStores,
    settings: ZebraAgentSettings,
) -> tuple[StreamHintRelay | None, Callable[[ProjectionCheckpointHead], object] | None]:
    """One Worker-owned publisher; cloud durable frontiers replace Event push wrappers."""
    if settings.live_events.redis_url is None:
        if settings.deployment == "cloud":
            raise ValueError("cloud checkpoint delivery requires Redis publication")
        return None, None
    namespace = getattr(stores, "deployment_namespace", None) or "local"
    publisher = RedisCommittedEventPublisher.from_url(
        settings.live_events.redis_url,
        deployment_namespace=namespace,
        max_stream_length=settings.live_events.stream_max_length,
        key_prefix=settings.live_events.key_prefix,
    ).fanout
    if settings.deployment == "cloud":
        if (not isinstance(stores, PostgresControlPlaneStores)
            or not isinstance(stores.tasks, PostgresAgentTaskStore)):

            publisher.close()
            raise ValueError("cloud stream relay requires PostgreSQL stores")
        return StreamHintRelay(
            stores.tasks._database._dsn, namespace, publisher
        ), publisher.publish_checkpoint
    return None, publisher.publish_checkpoint
