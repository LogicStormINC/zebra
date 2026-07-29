"""Worker-local tool gateway composition."""

from agent_core.domain.identifiers import SessionId
from agent_core.ports import ArtifactPayloadStorePort, ModelGatewayPort, SessionHistoryPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_runtime import LocalToolGateway
from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_scope import build_scoped_skill_roots
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


def build_worker_tool_gateway(
    task: RecoveredTask,
    *,
    settings: ZebraAgentSettings,
    model_gateway: ModelGatewayPort,
    session_history: SessionHistoryPort,
    session_id: SessionId,
    runtime: RuntimePort,
    runtime_handle: RuntimeHandle,
    local_artifacts: ArtifactPayloadStorePort,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
    trusted_local: bool,
) -> LocalToolGateway:
    skill_roots = build_scoped_skill_roots(
        system=settings.skill_roots_system,
        admin=settings.skill_roots_admin,
        user=settings.skill_roots,
        repo=settings.skill_roots_repo,
    )
    skills_enabled = any(
        (
            settings.skill_roots,
            settings.skill_roots_system,
            settings.skill_roots_admin,
            settings.skill_roots_repo,
        )
    )
    return LocalToolGateway(
        task.workspace_root,
        model_gateway=model_gateway,
        tool_profile=task.tool_profile,
        web_search_endpoint=settings.web_search_endpoint,
        skill_roots=skill_roots,
        skills_state=(
            SQLiteSkillsStateStore(settings.skills_state_path) if skills_enabled else None
        ),
        mcp_servers=settings.mcp_servers,
        mcp_allowlist=task.mcp_allowlist,
        session_history=session_history.scoped(task.history_session_ids),
        current_session_id=str(session_id),
        runtime=runtime,
        runtime_handle=runtime_handle,
        artifact_payload_store=local_artifacts if cloud_artifacts is None else None,
        output_projector=cloud_artifacts.output_projector if cloud_artifacts else None,
        trusted_local=trusted_local,
        web_pipeline_v2=settings.web_pipeline_v2,
    )
