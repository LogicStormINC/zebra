"""Local-profile inline execution adapter (AL-API-BOUNDARY-01).

The cloud API surface must not depend on Worker or Runtime execution. This
module is the one local composition seam that may import them, and it is
imported lazily only when the local profile actually executes inline. The
cloud command path never touches this module.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.image_attachments import ImageAttachmentContextInput, ImageAttachmentInput
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_integrations import ModelProviderSettings
from agent_security import PolicyProfile, parse_network_profile, resolve_effective_network_profile
from agent_storage import list_confirmed_repo_memories
from zebra_agent_config import trusted_local_mode_enabled

from zebra_agent_api.model_configuration import model_provider_settings
from zebra_agent_api.serialization import serialize_trace_events
from zebra_agent_api.session_attachment_persistence import persist_initial_attachments
from zebra_agent_api.session_payload_types import CreateSessionPayload
from zebra_agent_api.skills_admin import runtime_skills_state, scoped_skill_roots

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi

from agent_runtime import run_local_harness
from agent_storage import LeaseConflictError
from zebra_agent_worker import (
    SessionClaimService,
    SessionControlError,
    SessionControlService,
    SessionExecutionService,
    SessionRecoveryError,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
    WorkerExecutionError,
)

from zebra_agent_api.responses import ApiResponse, conflict, service_unavailable

__all__ = [
    "LeaseConflictError",
    "SessionControlError",
    "SessionControlService",
    "SessionClaimService",
    "SessionExecutionService",
    "SessionRecoveryError",
    "SessionRecoveryService",
    "SessionResumeError",
    "SessionResumeService",
    "WorkerExecutionError",
    "run_local_harness",
]


def map_execution_error(session_id: str, exc: BaseException) -> ApiResponse | None:
    """Map a Worker execution error to an API response, or None to raise."""

    from agent_core.domain.leases import LeaseConflictError  # noqa: PLC0415
    from zebra_agent_worker.execution_finalization import (  # noqa: PLC0415
        WorkerExecutionError,
    )
    from zebra_agent_worker.recovery import SessionRecoveryError  # noqa: PLC0415
    from zebra_agent_worker.resume import SessionResumeError  # noqa: PLC0415

    if isinstance(exc, SessionRecoveryError):
        return ApiResponse(
            status_code=404,
            body={"session_id": session_id, "status": "not_found"},
        )
    if isinstance(exc, SessionResumeError):
        return conflict(
            session_id=session_id,
            status="not_resumable",
            reason=(
                "awaiting_next_turn_message"
                if "awaiting the next turn" in str(exc)
                else "cannot_resume_terminal_session"
            ),
        )
    if isinstance(exc, LeaseConflictError):
        return conflict(
            session_id=session_id,
            status="lease_conflict",
            reason="session_already_leased",
        )
    if isinstance(exc, WorkerExecutionError):
        return conflict(
            session_id=session_id,
            status="execution_error",
            reason=str(exc),
        )
    if isinstance(exc, ValueError):
        return service_unavailable(
            status="model_gateway_unavailable",
            reason=str(exc),
        )
    return None


def create_and_execute_session(
    app: ZebraAgentApi,
    parsed: CreateSessionPayload,
    build_gateway: Callable[[ModelProviderSettings], ModelGatewayPort],
) -> ApiResponse:
    workspace_root = Path(str(parsed["workspace"])).expanduser().resolve()
    confirmed_memories = list_confirmed_repo_memories(
        app.stores.memories,
        repo_id=str(workspace_root),
    )
    try:
        model_gateway = build_gateway(model_provider_settings(app.settings))
    except ValueError as error:
        return service_unavailable(
            status="model_gateway_unavailable",
            reason=str(error),
        )
    try:
        trusted_local = trusted_local_mode_enabled(app.settings)
        network_profile = resolve_effective_network_profile(
            parse_network_profile(
                str(parsed["network_profile"]),
                domain_allowlist=parsed["network_allowlist"],
            ),
            trusted_local=trusted_local,
        )
        result = run_local_harness(
            prompt=str(parsed["prompt"]),
            title=str(parsed["title"]),
            workspace_root=workspace_root,
            model_gateway=model_gateway,
            policy_profile=PolicyProfile(str(parsed["policy_profile"])),
            tool_profile=ToolProfile(str(parsed["tool_profile"])),
            network_profile=network_profile,
            web_search_endpoint=app.settings.web_search_endpoint,
            skill_roots=scoped_skill_roots(app.settings),
            skills_state=runtime_skills_state(app.settings),
            mcp_servers=app.settings.mcp_servers,
            mcp_allowlist=parsed["mcp_allowlist"],
            trusted_local=trusted_local,
            max_model_calls=parsed["max_model_calls"],
            max_tool_calls=parsed["max_tool_calls"],
            session_history=app.stores.session_history.scoped(parsed["history_session_ids"]),
            confirmed_memories=confirmed_memories,
            attachments=tuple(
                AttachmentContextInput.model_validate(
                    {
                        **attachment.model_dump(exclude={"payload"}),
                        "text": attachment.payload.decode("utf-8"),
                    }
                )
                for attachment in parsed["attachments"]
                if not isinstance(attachment, ImageAttachmentInput)
            ),
            image_attachments=tuple(
                ImageAttachmentContextInput(
                    attachment_id=attachment.attachment_id,
                    file_name=attachment.file_name,
                    media_type=attachment.media_type,
                    payload=attachment.payload,
                    width=attachment.width,
                    height=attachment.height,
                    sha256=sha256(attachment.payload).hexdigest(),
                )
                for attachment in parsed["attachments"]
                if isinstance(attachment, ImageAttachmentInput)
            ),
        )
    except ValueError as error:
        return service_unavailable(
            status="tool_gateway_unavailable",
            reason=str(error),
        )
    events, attachment_refs = persist_initial_attachments(
        app.stores.artifact_payloads,
        tuple(result.events),
        parsed["attachments"],
    )
    for event in events:
        app.stores.events.append(event)
    app.stores.sessions.save_session(result.session)
    app.stores.workspaces.save_workspace(rebuild_workspace(list(events)))
    return ApiResponse(
        status_code=201,
        body={
            "session_id": str(result.session.session_id),
            "title": str(parsed["title"]),
            "prompt": str(parsed["prompt"]),
            "workspace": str(parsed["workspace"]),
            "executed": True,
            "status": result.session.status.value,
            "assistant_message": result.attempt_result.metadata.get("assistant_message"),
            "stop_reason": result.run_result.stop_reason.value,
            "attempts_used": result.run_result.attempts_used,
            "policy_profile": str(parsed["policy_profile"]),
            "tool_profile": str(parsed["tool_profile"]),
            "network_profile": str(parsed["network_profile"]),
            "network_allowlist": parsed["network_allowlist"],
            "mcp_allowlist": parsed["mcp_allowlist"],
            "mcp_resource_ids": parsed["mcp_resource_ids"],
            **(
                {"mcp_prompt_id": parsed["mcp_prompt_id"]}
                if parsed["mcp_prompt_id"] is not None
                else {}
            ),
            "trace": serialize_trace_events(tuple(result.events)),
            "attachments": [ref.to_mapping() for ref in attachment_refs],
        },
    )
