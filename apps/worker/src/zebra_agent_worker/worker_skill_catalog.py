"""Cloud Skill catalog wiring from one already recovered Turn snapshot."""

import asyncio
from dataclasses import dataclass

from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_core.ports import ArtifactObjectStorePort
from agent_core.ports.extensions import ExtensionStore
from agent_tools.cloud_skills import CloudSkillCatalog, prepare_cloud_skill_catalog
from agent_tools.skill_publications import SkillPublicationService
from agent_tools.skills_catalog import (
    SkillCatalog,
    SkillCatalogError,
    SkillMetadata,
    SkillReadResult,
)

from zebra_agent_worker.extension_recovery import RecoveredTurnExtension
from zebra_agent_worker.worker_plugins import WorkerPluginGuard


@dataclass(frozen=True, slots=True)
class WorkerSkillCatalogSource:
    store: ExtensionStore
    objects: ArtifactObjectStorePort
    publications: SkillPublicationService | None = None


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
    plugin_guard: WorkerPluginGuard | None = None,
) -> SkillCatalog | None:
    """Expose only an already trusted Turn snapshot; disabled paths do no I/O."""
    if source is None or extension is None:
        return None
    snapshot = extension.snapshot
    catalog = asyncio.run(
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

    if plugin_guard is None:
        return catalog
    return _PluginSkillCatalog(
        catalog.snapshot,
        catalog.scope,
        catalog.deployment_namespace,
        catalog.store,
        catalog.objects,
        plugin_guard,
    )


@dataclass(frozen=True)
class _PluginSkillCatalog(CloudSkillCatalog):
    guard: WorkerPluginGuard

    def list(self, *, limit: int = 100) -> tuple[tuple[SkillMetadata, ...], int, bool]:
        self.guard.validate()
        try:
            result = super().list(limit=limit)
        except SkillCatalogError as exc:
            _check_plugin_skill_failure(self.guard, exc)
            raise
        self.guard.validate()
        return result

    def read(self, name: str, *, file_path: str = "SKILL.md") -> SkillReadResult:
        self.guard.validate()
        try:
            result = super().read(name, file_path=file_path)
        except SkillCatalogError as exc:
            _check_plugin_skill_failure(self.guard, exc)
            raise
        self.guard.validate()
        return result


def _check_plugin_skill_failure(guard: WorkerPluginGuard, error: SkillCatalogError) -> None:
    guard.validate()
    snapshot = guard.extension.snapshot
    if error.reason in {
        "installation_unavailable",
        "publication_unavailable",
        "package_integrity",
        "backend_unavailable",
    } and any(c.kind == "skill-bundle" for p in snapshot.plugins for c in p.components):
        raise PluginAuthorityUnavailable("selected plugin Skill source is unavailable") from None
