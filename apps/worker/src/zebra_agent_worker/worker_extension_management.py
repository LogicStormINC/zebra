"""Optional native configuration tools; no synthetic grants or mutable tool selection."""

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_runtime.github_skill_import import GitHubSkillImportError, import_github_skill
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_security.extension_worker_authority import ExtensionWorkerAuthority
from agent_tools.extension_management import ExtensionManagementTools

from zebra_agent_worker.extension_recovery import RecoveredTurnExtension
from zebra_agent_worker.worker_mcp_catalog import WorkerMcpSource
from zebra_agent_worker.worker_skill_catalog import WorkerSkillCatalogSource


def prepare_extension_management(
    extension: RecoveredTurnExtension | None, *, mcp: WorkerMcpSource | None,
    skills: WorkerSkillCatalogSource | None, session_id: SessionId, fence: LeaseFence,
    allow_network: bool = False,
) -> ExtensionManagementTools | None:
    if extension is None or mcp is None or skills is None:
        return None
    context = extension.task_ceiling.binding.host_capability.host_context
    if context is None or not {"extensions.read", "extensions.manage"} & set(context.scopes):
        return None
    authority = ExtensionWorkerAuthority(
        session_id=session_id, expected_scope=extension.scope, fence=fence,
        tasks=mcp.release.tasks, leases=mcp.leases,
        fresh_authority=lambda: mcp.execution_authority(session_id, extension.snapshot.turn_id),
    )

    async def refresh(connection_id: str, revision: int) -> int:
        if mcp.refresh is None:
            raise ValueError("MCP management refresh is not configured")
        service: McpCatalogRefresh = mcp.refresh

        def revalidate() -> None:
            authority("extensions.manage")

        catalog = await service.refresh_authorized(
            scope=authority("extensions.manage"), connection_id=connection_id,
            expected_revision=revision, revalidate=revalidate,
        )
        return len(catalog.tools)

    async def import_skill(url: str, path: str | None, key: str) -> dict[str, object]:
        scope = authority("extensions.manage")

        def revalidate() -> None:
            if authority("extensions.manage") != scope:
                raise ValueError("Skill import scope changed")

        try:
            imported = await import_github_skill(url, path=path, revalidate=revalidate)
        except GitHubSkillImportError as exc:
            return {"status": exc.reason, "candidates": list(exc.candidates), "usable": False}
        assert skills.publications is not None
        publication = await skills.publications.publish(
            archive=imported.archive, scope=scope, idempotency_key=key, before_save=revalidate,
        )
        return {"skill_id": publication.version.skill_id,
                "version_id": publication.version.version_id,
                "name": publication.name, "source_url": imported.source_url,
                "commit_sha": imported.commit_sha, "path": imported.skill_path}

    return ExtensionManagementTools(
        skills.store, authority, refresh if mcp.refresh and allow_network else None,
        import_skill if skills.publications and allow_network else None,
    )
