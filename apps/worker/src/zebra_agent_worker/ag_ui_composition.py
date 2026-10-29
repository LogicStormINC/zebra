"""Explicit process-owned projection composition, shared standard profiles default off."""

from collections.abc import Callable

from agent_core.ports.task_projection_checkpoints import ProjectionCheckpointHead
from agent_core.ports.task_projection_work import TaskProjectionWorkPort
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.ag_ui.standard_profiles import standard_profiles
from agent_storage import ControlPlaneStores, PostgresControlPlaneStores
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.ag_ui_projection_work import AgUiProjectionWorkService


def configure_agui_projection_work(
    stores: ControlPlaneStores | PostgresControlPlaneStores,
    settings: ZebraAgentSettings,
    namespace: str | None,
    checkpoint_committed: Callable[[ProjectionCheckpointHead], object] | None,
) -> AgUiProjectionWorkService | None:
    if stores.projection_work is None:
        if settings.stream.agui_profiles_enabled:
            raise ValueError("AG-UI profile composition requires projection work stores")
        return None

    def consumer(
        work: TaskProjectionWorkPort, profile: AgUiProjectionProfile | None = None
    ) -> AgUiCheckpointConsumer:
        return AgUiCheckpointConsumer(
            stores.tasks,
            work,
            namespace=namespace or "local",
            checkpoint_committed=checkpoint_committed,
            notification_required=settings.deployment == "cloud",
            read_summaries=stores.tasks if isinstance(stores, PostgresControlPlaneStores) else None,
            profile=profile,
        )

    legacy = consumer(stores.projection_work)
    coverage = (
        consumer(stores.coverage_projection_work)
        if stores.coverage_projection_work is not None
        else None
    )
    additional = []
    if settings.stream.agui_profiles_enabled:
        factory = stores.projection_work_for_version
        if factory is None:
            raise ValueError("AG-UI profiles require exact version work composition")
        for profile in standard_profiles(
            interactions=settings.stream.agui_native_interaction_enabled
        ):
            for strict in (False, True):
                additional.append(
                    consumer(factory(profile.checkpoint_version(coverage=strict)), profile)
                )
    return AgUiProjectionWorkService(
        legacy, coverage_consumer=coverage, additional_consumers=tuple(additional)
    )
