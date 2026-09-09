"""Cloud Skill catalog wiring from one already recovered Turn snapshot."""

import asyncio
from dataclasses import dataclass

from agent_core.ports import ArtifactObjectStorePort
from agent_core.ports.extensions import ExtensionStore
from agent_tools.cloud_skills import prepare_cloud_skill_catalog
from agent_tools.skills_catalog import SkillCatalog

from zebra_agent_worker.extension_recovery import RecoveredTurnExtension


@dataclass(frozen=True, slots=True)
class WorkerSkillCatalogSource:
    store: ExtensionStore
    objects: ArtifactObjectStorePort


def require_recovery[T](
    extension_store: T | None,
    source: WorkerSkillCatalogSource | None,
) -> tuple[T | None, WorkerSkillCatalogSource | None]:
    if source is not None and extension_store is None:
        raise ValueError("cloud Skills require extension snapshot recovery")
    return extension_store, source


def prepare_worker_skill_catalog(
    extension: RecoveredTurnExtension | None,
    *,
    deployment_namespace: str,
    source: WorkerSkillCatalogSource | None,
) -> SkillCatalog | None:
    """Expose only an already trusted Turn snapshot; disabled paths do no I/O."""
    if source is None or extension is None:
        return None
    snapshot = extension.snapshot
    return asyncio.run(
        prepare_cloud_skill_catalog(
            snapshot=snapshot,
            scope=extension.scope,
            deployment_namespace=deployment_namespace,
            session_id=snapshot.session_id,
            turn_id=snapshot.turn_id,
            store=source.store,
            objects=source.objects,
        )
    )
