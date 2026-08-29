"""Compose durable replay with best-effort Redis live delivery."""

from agent_core.ports import WorkerProjectionTransactionPort
from agent_integrations import RedisCommittedEventPublisher
from agent_storage import (
    ControlPlaneStores,
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
    if settings.live_events.redis_url is None:
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
