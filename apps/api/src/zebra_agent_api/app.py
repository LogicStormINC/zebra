from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import ArtifactId, SessionId, new_event_id
from agent_core.domain.model_media import ModelMediaInput
from agent_core.domain.skills import SkillComponentIdentity
from agent_core.domain.tool_profiles import ToolProfile
from agent_integrations import GitHubPullRequestTransport, build_model_gateway
from agent_runtime import (
    bind_native_media_inputs,
    read_mcp_resource_attachments,
    run_local_harness,
    validate_mcp_capability_selection,
)
from agent_security import (
    CredentialBroker,
    PolicyProfile,
    parse_network_profile,
    resolve_effective_network_profile,
)
from agent_storage import (
    LeaseConflictError,
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteSessionHistory,
    SQLiteWorkspaceProjectionStore,
    list_confirmed_repo_memories,
)
from agent_storage.session_attachments import RegisteredTaskMedia, TaskAttachmentMediaResolver
from agent_tools.skills_catalog import LocalSkillCatalog
from zebra_agent_config import (
    ModelCatalogEntry,
    ZebraAgentSettings,
    load_settings,
    select_model_catalog_entry,
    settings_for_model,
    trusted_local_mode_enabled,
    with_task_workspace_root,
)
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryError,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
    WorkerExecutionError,
)

import zebra_agent_api.preapproved_tools as auth
import zebra_agent_api.session_payloads as payloads
from zebra_agent_api.agent_definition_binding import bind_server_resolved_agent_definition
from zebra_agent_api.api_approval_control_mixin import ApiApprovalControlMixin
from zebra_agent_api.api_artifact_read_mixin import ApiArtifactReadMixin
from zebra_agent_api.api_memory_control_mixin import ApiMemoryControlMixin
from zebra_agent_api.api_memory_read_mixin import ApiMemoryReadMixin
from zebra_agent_api.api_scm_mixin import ApiScmMixin
from zebra_agent_api.api_session_handoff_mixin import ApiSessionHandoffMixin
from zebra_agent_api.api_session_message_append_mixin import ApiSessionMessageAppendMixin
from zebra_agent_api.api_session_read_mixin import ApiSessionReadMixin
from zebra_agent_api.api_status_mixin import ApiStatusMixin
from zebra_agent_api.credential_broker import build_default_credential_broker
from zebra_agent_api.execution_context_lifecycle import persist_execution_events
from zebra_agent_api.idempotency import replay_idempotent_response, save_idempotent_response
from zebra_agent_api.responses import ApiResponse, bad_request, conflict, service_unavailable
from zebra_agent_api.serialization import serialize_trace_events
from zebra_agent_api.session_attachment_persistence import persist_initial_attachments
from zebra_agent_api.session_control import cancel_session_control, suspend_session_control
from zebra_agent_api.session_prompt_inputs import resolve_mcp_prompt_attachment
from zebra_agent_api.skills_admin import (
    ApiSkillsAdminMixin,
    runtime_skills_state,
    scoped_skill_roots,
)
from zebra_agent_api.task_final_identity import final_message_identity
from zebra_agent_api.task_image_attachments import (
    StagedTaskImages,
    cleanup_staged_task_images,
    stage_task_images,
    task_image_prompt_suffix,
)


@dataclass(frozen=True)
class ZebraAgentApi(
    ApiStatusMixin,
    ApiSessionMessageAppendMixin,
    ApiSessionReadMixin,
    ApiSessionHandoffMixin,
    ApiMemoryReadMixin,
    ApiArtifactReadMixin,
    ApiMemoryControlMixin,
    ApiScmMixin,
    ApiApprovalControlMixin,
    ApiSkillsAdminMixin,
):
    database_path: Path
    settings: ZebraAgentSettings
    credential_broker: CredentialBroker | None = None
    github_transport: GitHubPullRequestTransport | None = None

    def create_session(
        self,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
        session_id: SessionId | None = None,
    ) -> ApiResponse:
        replayed = replay_idempotent_response(
            database_path=self.database_path,
            action="session.create",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replayed is not None:
            return replayed
        parsed = payloads.parse_create_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        try:
            model_entry = select_model_catalog_entry(self.settings, parsed["model"])
        except ValueError as error:
            return bad_request(str(error))
        try:
            parsed["agent_definition"] = bind_server_resolved_agent_definition(
                parsed["agent_definition"],
                self.settings,
            )
        except ValueError as error:
            return bad_request(str(error))
        try:
            skill_grant = _skill_grant_snapshot(
                self.settings, parsed["skill_components"]
            )
        except ValueError as error:
            return bad_request(str(error))
        if trusted_local_mode_enabled(self.settings) and not auth.is_scoped(parsed):
            parsed["network_profile"] = "full-trusted-local"
            parsed["network_allowlist"] = []
        try:
            validate_mcp_capability_selection(
                self.settings.mcp_servers,
                parsed["mcp_allowlist"],
            )
        except ValueError as error:
            return bad_request(str(error))
        try:
            resource_attachments = read_mcp_resource_attachments(
                self.settings.mcp_servers,
                parsed["mcp_resource_ids"],
            )
        except ValueError as error:
            return bad_request(str(error))
        try:
            prompt_attachments = resolve_mcp_prompt_attachment(
                self.settings.mcp_servers,
                parsed["mcp_prompt_id"],
                parsed["mcp_prompt_arguments"],
            )
        except ValueError as error:
            return bad_request(str(error))
        parsed["attachments"] = (*parsed["attachments"], *resource_attachments, *prompt_attachments)
        session_id = session_id or (SessionId(uuid4()) if parsed["image_attachments"] else None)
        response = (
            self._create_and_execute_session(
                parsed,
                model_entry=model_entry,
                session_id=session_id,
                skill_grant=skill_grant,
            )
            if parsed["execute"]
            else self._create_queued_session(
                parsed,
                model_entry=model_entry,
                session_id=session_id,
                skill_grant=skill_grant,
            )
        )
        if idempotency_key is None or response.status_code != 201:
            return response
        return save_idempotent_response(
            database_path=self.database_path,
            action="session.create",
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
        )
    def resume_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        parsed = payloads.parse_resume_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        claim_service = SessionClaimService(
            SQLiteLeaseStore(self.database_path),
            SessionRecoveryService(
                SQLiteEventStore(self.database_path),
                SQLiteProjectionStore(self.database_path),
            ),
        )
        try:
            result = SessionExecutionService(
                database_path=self.database_path,
                claim_service=claim_service,
                resume_service=SessionResumeService(claim_service),
                settings=self.settings,
            ).execute_session(
                session_key,
                worker_id=parsed["worker_id"],
                lease_ttl_seconds=parsed["lease_ttl_seconds"],
            )
        except SessionRecoveryError:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        except SessionResumeError:
            return conflict(
                session_id=session_id,
                status="not_resumable",
                reason="cannot_resume_terminal_session",
            )
        except LeaseConflictError:
            return conflict(
                session_id=session_id,
                status="lease_conflict",
                reason="session_already_leased",
            )
        except WorkerExecutionError as error:
            return conflict(
                session_id=session_id,
                status="execution_error",
                reason=str(error),
            )
        except ValueError as error:
            return service_unavailable(
                status="model_gateway_unavailable",
                reason=str(error),
            )
        final_message = final_message_identity(self.database_path, session_id)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "executed": True,
                "worker_id": parsed["worker_id"],
                "status": result.session.status.value,
                "current_sequence": result.session.current_sequence,
                "assistant_message": result.attempt_result.metadata.get("assistant_message"),
                "trace": serialize_trace_events(result.events),
                "artifact_output_contract": result.attempt_result.metadata.get(
                    "output_contract"
                ),
                **(
                    {"final_message": final_message}
                    if final_message is not None
                    else {}
                ),
            },
        )
    def cancel_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return cancel_session_control(self.database_path, str(session_key), payload)
    def suspend_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return suspend_session_control(self.database_path, str(session_key), payload)

    def _parse_session_id(self, session_id: str) -> SessionId | ApiResponse:
        try:
            return SessionId(UUID(session_id))
        except ValueError:
            return ApiResponse(
                status_code=400,
                body={
                    "session_id": session_id,
                    "status": "invalid_request",
                    "reason": "session_id must be a valid UUID",
                },
            )

    def _create_queued_session(
        self,
        parsed: payloads.CreateSessionPayload,
        *,
        model_entry: ModelCatalogEntry,
        session_id: SessionId | None,
        skill_grant: tuple[
            tuple[str, ...], tuple[SkillComponentIdentity, ...]
        ],
    ) -> ApiResponse:
        try:
            staged_images = (
                stage_task_images(
                    self.settings,
                    task_id=str(session_id),
                    images=parsed["image_attachments"],
                )
                if parsed["image_attachments"]
                else None
            )
        except ValueError as error:
            return bad_request(str(error))
        images_durable = False
        try:
            skill_components, skill_component_identities = skill_grant
            bootstrap = SessionBootstrapService().build(
                SessionBootstrapCommand(
                    title=str(parsed["title"]),
                    user_input=str(parsed["prompt"]),
                    public_content=parsed["public_content"], workspace_root=(
                        staged_images.workspace_root
                        if staged_images is not None
                        else Path(str(parsed["workspace"])).expanduser().resolve()
                    ),
                    policy_profile=str(parsed["policy_profile"]),
                    tool_profile=ToolProfile(str(parsed["tool_profile"])),
                    network_profile=str(parsed["network_profile"]),
                    network_allowlist=tuple(parsed["network_allowlist"]),
                    skill_components=skill_components,
                    skill_component_identities=skill_component_identities,
                    **auth.command_fields(parsed),
                    history_session_ids=parsed["history_session_ids"],
                    max_model_calls=parsed["max_model_calls"],
                    max_tool_calls=parsed["max_tool_calls"],
                    agent_definition=parsed["agent_definition"],
                    model_id=model_entry.id,
                    session_id=session_id,
                )
            )
            events, attachment_refs = persist_initial_attachments(
                self.database_path,
                tuple(bootstrap.events),
                parsed["attachments"],
                staged_images=staged_images,
            )
            event_store = SQLiteEventStore(self.database_path)
            for event in events:
                event_store.append(event)
                images_durable |= event.event_type is EventType.USER_MESSAGE_RECEIVED
            SQLiteProjectionStore(self.database_path).save_session(bootstrap.session)
            SQLiteWorkspaceProjectionStore(self.database_path).save_workspace(
                rebuild_workspace(list(events))
            )
        except Exception:
            if staged_images is not None and not images_durable:
                cleanup_staged_task_images(staged_images)
            raise
        return ApiResponse(
            status_code=201,
            body={
                "session_id": str(bootstrap.session.session_id),
                "title": str(parsed["title"]),
                "prompt": str(parsed["prompt"]),
                "workspace": str(parsed["workspace"]),
                "executed": False,
                "model": model_entry.id,
                "status": bootstrap.session.status.value,
                "tool_profile": str(parsed["tool_profile"]),
                "max_model_calls": parsed["max_model_calls"],
                "max_tool_calls": parsed["max_tool_calls"],
                "network_profile": str(parsed["network_profile"]),
                "network_allowlist": parsed["network_allowlist"],
                **auth.response_fields(parsed),
                "mcp_resource_ids": parsed["mcp_resource_ids"],
                **(
                    {"history_session_ids": list(parsed["history_session_ids"])}
                    if parsed["history_session_ids"] is not None
                    else {}
                ),
                **(
                    {"mcp_prompt_id": parsed["mcp_prompt_id"]}
                    if parsed["mcp_prompt_id"] is not None
                    else {}
                ),
                "attachments": [ref.to_mapping() for ref in attachment_refs],
                **_agent_definition_response(parsed),
            },
        )

    def _create_and_execute_session(
        self,
        parsed: payloads.CreateSessionPayload,
        *,
        model_entry: ModelCatalogEntry,
        session_id: SessionId | None,
        skill_grant: tuple[
            tuple[str, ...], tuple[SkillComponentIdentity, ...]
        ],
    ) -> ApiResponse:
        try:
            model_gateway = build_model_gateway(
                settings_for_model(self.settings, model_entry.id)
            )
        except ValueError as error:
            return service_unavailable(
                status="model_gateway_unavailable",
                reason=str(error),
            )
        try:
            staged_images = (
                stage_task_images(
                    self.settings,
                    task_id=str(session_id),
                    images=parsed["image_attachments"],
                )
                if parsed["image_attachments"]
                else None
            )
        except ValueError as error:
            return bad_request(str(error))
        images_durable = False
        image_payload_store: SQLiteArtifactPayloadStore | None = None
        staged_payload_ids: tuple[ArtifactId, ...] = ()
        initial_user_event_id = new_event_id() if staged_images is not None else None
        native_media_inputs: tuple[ModelMediaInput, ...] = ()
        if staged_images is not None:
            if session_id is None or initial_user_event_id is None:
                cleanup_staged_task_images(staged_images)
                raise RuntimeError("inline task image session identity was not allocated")
            image_payload_store = SQLiteArtifactPayloadStore(self.database_path)
            try:
                staged_payload_ids = staged_images.persist_payloads(
                    image_payload_store,
                    session_id=session_id,
                    created_at=datetime.now(UTC),
                )
                image_refs = staged_images.refs_for(initial_user_event_id)
                media_resolver = TaskAttachmentMediaResolver(
                    image_payload_store,
                    tuple(
                        RegisteredTaskMedia(
                            attachment=image_ref,
                            source_session_id=session_id,
                        )
                        for image_ref in image_refs
                    ),
                )
                native_media_inputs = bind_native_media_inputs(
                    model_gateway,
                    media_resolver.media_inputs,
                    media_resolver,
                )
            except Exception as error:
                _cleanup_uncommitted_staged_images(
                    staged_images,
                    image_payload_store,
                    staged_payload_ids,
                )
                if not isinstance(error, ValueError):
                    raise
                return service_unavailable(
                    status="model_gateway_unavailable",
                    reason=str(error),
                )
        workspace_root = (
            staged_images.workspace_root
            if staged_images is not None
            else Path(str(parsed["workspace"])).expanduser().resolve()
        )
        confirmed_memories = list_confirmed_repo_memories(
            self.database_path,
            repo_id=str(workspace_root),
        )
        try:
            trusted_local = trusted_local_mode_enabled(self.settings) and not auth.is_scoped(parsed)
            network_profile = resolve_effective_network_profile(
                parse_network_profile(
                    str(parsed["network_profile"]),
                    domain_allowlist=parsed["network_allowlist"],
                ),
                trusted_local=trusted_local,
            )
            result = run_local_harness(
                prompt=str(parsed["prompt"])
                + (
                    task_image_prompt_suffix(staged_images)
                    if staged_images is not None and not native_media_inputs
                    else ""
                ),
                public_content=parsed["public_content"], title=str(parsed["title"]),
                workspace_root=workspace_root,
                model_gateway=model_gateway,
                policy_profile=PolicyProfile(str(parsed["policy_profile"])),
                tool_profile=ToolProfile(str(parsed["tool_profile"])),
                network_profile=network_profile,
                web_search_endpoint=self.settings.web_search_endpoint,
                skill_roots=scoped_skill_roots(self.settings),
                skills_state=runtime_skills_state(self.settings),
                granted_skill_component_identities=skill_grant[1],
                mcp_servers=(
                    with_task_workspace_root(
                        self.settings.mcp_servers, staged_images.workspace_root
                    )
                    if staged_images is not None
                    else self.settings.mcp_servers
                ),
                **auth.command_fields(parsed),
                trusted_local=trusted_local,
                max_model_calls=parsed["max_model_calls"],
                max_tool_calls=parsed["max_tool_calls"],
                agent_definition=parsed["agent_definition"],
                model_id=model_entry.id,
                session_history=SQLiteSessionHistory(
                    self.database_path, allowed_session_ids=parsed["history_session_ids"]
                ),
                confirmed_memories=confirmed_memories,
                attachments=tuple(
                    AttachmentContextInput.model_validate(
                        {
                            **attachment.model_dump(exclude={"payload"}),
                            "text": attachment.payload.decode("utf-8"),
                        }
                    )
                    for attachment in parsed["attachments"]
                ),
                media_inputs=native_media_inputs,
                disabled_mcp_tools=(
                    ("mcp.minimax.understand_image",) if native_media_inputs else ()
                ),
                session_id=session_id,
                initial_user_event_id=initial_user_event_id,
            )
        except Exception as error:
            if staged_images is not None and not images_durable:
                _cleanup_uncommitted_staged_images(
                    staged_images,
                    image_payload_store,
                    staged_payload_ids,
                )
            if not isinstance(error, ValueError):
                raise
            return service_unavailable(
                status="tool_gateway_unavailable",
                reason=str(error),
            )
        try:
            events, attachment_refs = persist_initial_attachments(
                self.database_path,
                tuple(result.events),
                parsed["attachments"],
                staged_images=staged_images,
            )
            session = persist_execution_events(self.database_path, events)
            images_durable = staged_images is not None
        except Exception:
            if staged_images is not None and not images_durable:
                if not any(
                    event.event_type is EventType.USER_MESSAGE_RECEIVED
                    for event in SQLiteEventStore(self.database_path).list_for_session(
                        result.session.session_id
                    )
                ):
                    _cleanup_uncommitted_staged_images(
                        staged_images,
                        image_payload_store,
                        staged_payload_ids,
                    )
            raise
        final_message = final_message_identity(
            self.database_path, str(session.session_id)
        )
        return ApiResponse(
            status_code=201,
            body={
                "session_id": str(session.session_id),
                "title": str(parsed["title"]),
                "prompt": str(parsed["prompt"]),
                "workspace": str(parsed["workspace"]),
                "executed": True,
                "model": model_entry.id,
                "status": session.status.value,
                "assistant_message": result.attempt_result.metadata.get("assistant_message"),
                "artifact_output_contract": result.attempt_result.metadata.get(
                    "output_contract"
                ),
                **({"final_message": final_message} if final_message is not None else {}),
                "stop_reason": result.run_result.stop_reason.value,
                "attempts_used": result.run_result.attempts_used,
                "policy_profile": str(parsed["policy_profile"]),
                "tool_profile": str(parsed["tool_profile"]),
                "network_profile": str(parsed["network_profile"]),
                "network_allowlist": parsed["network_allowlist"],
                **auth.response_fields(parsed),
                "mcp_resource_ids": parsed["mcp_resource_ids"],
                **(
                    {"mcp_prompt_id": parsed["mcp_prompt_id"]}
                    if parsed["mcp_prompt_id"] is not None
                    else {}
                ),
                "trace": serialize_trace_events(tuple(result.events)),
                "attachments": [ref.to_mapping() for ref in attachment_refs],
                **_agent_definition_response(parsed),
            },
        )


def _cleanup_uncommitted_staged_images(
    staged_images: StagedTaskImages,
    payload_store: SQLiteArtifactPayloadStore | None,
    payload_ids: tuple[ArtifactId, ...],
) -> None:
    cleanup_staged_task_images(staged_images)
    if payload_store is None:
        return
    for artifact_id in payload_ids:
        payload_store.prune_payload(artifact_id)


def _agent_definition_response(
    parsed: payloads.CreateSessionPayload,
) -> dict[str, object]:
    definition = parsed["agent_definition"]
    return {} if definition is None else {"agent_definition": definition.model_dump(mode="json")}


def _skill_grant_snapshot(
    settings: ZebraAgentSettings,
    requested: tuple[str, ...] | None = None,
) -> tuple[tuple[str, ...], tuple[SkillComponentIdentity, ...]]:
    roots = scoped_skill_roots(settings)
    if not roots:
        if requested:
            raise ValueError("requested Skill component is unavailable")
        return (), ()
    metadata = LocalSkillCatalog(
        roots,
        skills_state=runtime_skills_state(settings),
    ).list()[0]
    available = {item.name: item.component_identity() for item in metadata}
    selected = tuple(available) if requested is None else requested
    if any(name not in available for name in selected):
        raise ValueError("requested Skill component is unavailable")
    identities = tuple(available[name] for name in selected)
    return tuple(identity.name for identity in identities), identities


def create_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    credential_broker: CredentialBroker | None = None,
    credential_env: Mapping[str, str] | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
) -> ZebraAgentApi:
    active_settings = settings or load_settings()
    active_broker = credential_broker
    if active_broker is None:
        active_broker = build_default_credential_broker(
            active_settings.scm,
            env=credential_env,
        )
    return ZebraAgentApi(
        database_path=Path(database_path or active_settings.database_url),
        settings=active_settings,
        credential_broker=active_broker,
        github_transport=github_transport,
    )
