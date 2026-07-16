from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.attachments import (
    AttachmentContextInput,
    SessionAttachmentRef,
    TextAttachmentInput,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.harness.models import HarnessAttemptTrace, HarnessLoopResult
from agent_core.harness.projection import HarnessTraceProjector
from agent_integrations import build_model_gateway
from agent_runtime import run_local_harness
from agent_security import DEFAULT_NETWORK_PROFILE, NetworkProfile, PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteSessionHistory,
    SQLiteWorkspaceProjectionStore,
    list_confirmed_repo_memories,
    store_initial_text_attachments,
)
from zebra_agent_config import ZebraAgentSettings


@dataclass(frozen=True)
class DurableRunResult:
    harness_result: HarnessLoopResult
    workspace_root: Path
    policy_profile: str
    tool_profile: str
    network_profile: str
    network_allowlist: tuple[str, ...]
    mcp_allowlist: tuple[str, ...]
    attachments: tuple[SessionAttachmentRef, ...] = ()


def execute_durable_run(
    *,
    prompt: str,
    title: str,
    workspace_root: Path,
    database_path: Path,
    settings: ZebraAgentSettings,
    policy_profile: PolicyProfile = PolicyProfile.WORKSPACE_WRITE,
    tool_profile: ToolProfile = ToolProfile.GENERAL,
    network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE,
    mcp_allowlist: tuple[str, ...] = (),
    attachments: tuple[TextAttachmentInput, ...] = (),
) -> DurableRunResult:
    confirmed_memories = list_confirmed_repo_memories(
        database_path,
        repo_id=str(workspace_root.resolve()),
    )
    result = run_local_harness(
        prompt=prompt,
        title=title,
        workspace_root=workspace_root,
        model_gateway=build_model_gateway(settings),
        policy_profile=policy_profile,
        tool_profile=tool_profile,
        network_profile=network_profile,
        web_search_endpoint=settings.web_search_endpoint,
        skill_roots=settings.skill_roots,
        mcp_servers=settings.mcp_servers,
        mcp_allowlist=mcp_allowlist,
        session_history=SQLiteSessionHistory(database_path),
        confirmed_memories=confirmed_memories,
        attachments=tuple(
            AttachmentContextInput(
                attachment_id=attachment.attachment_id,
                file_name=attachment.file_name,
                media_type=attachment.media_type,
                text=attachment.payload.decode("utf-8"),
                source_type=attachment.source_type,
                source_server=attachment.source_server,
                source_id=attachment.source_id,
            )
            for attachment in attachments
        ),
    )
    events, attachment_refs = store_initial_text_attachments(
        SQLiteArtifactPayloadStore(database_path),
        result.events,
        attachments,
    )
    result = replace(result, events=events)
    event_store = SQLiteEventStore(database_path)
    for event in result.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(result.session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(list(result.events))
    )
    return DurableRunResult(
        harness_result=result,
        workspace_root=workspace_root,
        policy_profile=policy_profile.value,
        tool_profile=tool_profile.value,
        network_profile=network_profile.name.value,
        network_allowlist=network_profile.domain_allowlist,
        mcp_allowlist=mcp_allowlist,
        attachments=attachment_refs,
    )


def serialize_run_execution(result: DurableRunResult) -> dict[str, object]:
    harness_result = result.harness_result
    return {
        "executed": True,
        "status": harness_result.session.status.value,
        "attempts_used": harness_result.run_result.attempts_used,
        "stop_reason": harness_result.run_result.stop_reason.value,
        "assistant_message": harness_result.attempt_result.metadata.get("assistant_message"),
        "policy_profile": result.policy_profile,
        "tool_profile": result.tool_profile,
        "network_profile": result.network_profile,
        "network_allowlist": list(result.network_allowlist),
        "mcp_allowlist": list(result.mcp_allowlist),
        "attachments": [attachment.to_mapping() for attachment in result.attachments],
        "workspace_root": str(result.workspace_root),
        "trace": _serialize_trace(HarnessTraceProjector().project(harness_result).attempts),
    }


def serialize_trace_events(events: tuple[SessionEvent, ...]) -> list[dict[str, object]]:
    return _serialize_trace(HarnessTraceProjector().project_events(events))


def _serialize_trace(attempts: tuple[HarnessAttemptTrace, ...]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for attempt in attempts:
        serialized.append(
            {
                "attempt_number": attempt.attempt_number,
                "assistant_message": attempt.assistant_message,
                "tools": [
                    {
                        "tool_name": tool.tool_name,
                        "status": tool.status,
                        "arguments": tool.arguments,
                        "output": tool.output,
                        "metadata": tool.metadata,
                        "policy_decision": tool.policy_decision,
                    }
                    for tool in attempt.tools
                ],
            }
        )
    return serialized
