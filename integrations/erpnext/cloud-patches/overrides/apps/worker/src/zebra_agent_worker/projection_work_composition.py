from __future__ import annotations

from agent_storage import PostgresControlPlaneStores


def build_projection_work(
    execution_stores,
    active_namespace,
    checkpoint_committed,
    settings,
    *,
    projection_factory,
    consumer_factory,
):
    return (
        projection_factory(
            consumer_factory(
                execution_stores.tasks,
                execution_stores.projection_work,
                namespace=active_namespace or "local",
                checkpoint_committed=checkpoint_committed,
                notification_required=settings.deployment == "cloud",
                read_summaries=execution_stores.tasks
                if isinstance(execution_stores, PostgresControlPlaneStores)
                else None,
            ),
            coverage_consumer=consumer_factory(
                execution_stores.tasks,
                execution_stores.coverage_projection_work,
                namespace=active_namespace or "local",
                checkpoint_committed=checkpoint_committed,
                notification_required=settings.deployment == "cloud",
                read_summaries=execution_stores.tasks
                if isinstance(execution_stores, PostgresControlPlaneStores)
                else None,
            )
            if execution_stores.coverage_projection_work is not None
            else None,
        )
        if execution_stores.projection_work is not None
        else None
    )
