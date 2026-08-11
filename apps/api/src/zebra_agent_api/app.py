from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    attach_refs_to_user_event,
)
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.ports import LiveEventFanoutPort
from agent_integrations import (
    GitHubPullRequestTransport,
    ModelProviderSettings,
    build_model_gateway,
)
from agent_runtime import (
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
    ControlPlaneStores,
    LeaseConflictError,
    list_confirmed_repo_memories,
    store_text_attachments,
)
from zebra_agent_config import (
    ZebraAgentSettings,
    trusted_local_mode_enabled,
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

from zebra_agent_api.api_approval_control_mixin import ApiApprovalControlMixin
from zebra_agent_api.api_artifact_read_mixin import ApiArtifactReadMixin
from zebra_agent_api.api_command_mixin import ApiCommandMixin
from zebra_agent_api.api_memory_control_mixin import ApiMemoryControlMixin
from zebra_agent_api.api_memory_read_mixin import ApiMemoryReadMixin
from zebra_agent_api.api_scm_mixin import ApiScmMixin
from zebra_agent_api.api_session_handoff_mixin import ApiSessionHandoffMixin
from zebra_agent_api.api_session_read_mixin import ApiSessionReadMixin
from zebra_agent_api.api_status_mixin import ApiStatusMixin
from zebra_agent_api.factory import create_app as create_app
from zebra_agent_api.idempotency import replay_idempotent_response, save_idempotent_response
from zebra_agent_api.responses import ApiResponse, bad_request, conflict, service_unavailable
from zebra_agent_api.serialization import serialize_trace_events
from zebra_agent_api.session_attachment_persistence import persist_initial_attachments
from zebra_agent_api.session_control import cancel_session_control, suspend_session_control
from zebra_agent_api.session_identity_read import _parse_session_id as parse_session_id
from zebra_agent_api.session_payloads import (
    CreateSessionPayload,
    parse_append_session_message_payload,
    parse_create_session_payload,
    parse_resume_session_payload,
)
from zebra_agent_api.session_prompt_inputs import resolve_mcp_prompt_attachment
from zebra_agent_api.session_queue import create_queued_session
from zebra_agent_api.skills_admin import (
    ApiSkillsAdminMixin,
    runtime_skills_state,
    scoped_skill_roots,
)
from zebra_agent_api.storage_composition import ControlPlaneStorageMixin


@dataclass(frozen=True)
class ZebraAgentApi(
    ControlPlaneStorageMixin,
    ApiStatusMixin,
    ApiCommandMixin,
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
    _stores: ControlPlaneStores | None = None
    live_event_fanout: LiveEventFanoutPort | None = None
    administrative_context_namespace: str | None = None
    credential_broker: CredentialBroker | None = None
    github_transport: GitHubPullRequestTransport | None = None
    _parse_session_id = staticmethod(parse_session_id)

    def create_session(
        self,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
        host_context: HostContextEnvelope | None = None,
    ) -> ApiResponse:
        replayed = (
            replay_idempotent_response(
                store=self.stores.idempotency,
                action="session.create",
                idempotency_key=idempotency_key,
                payload=payload,
            )
            if idempotency_key is not None
            else None
        )
        if replayed is not None:
            return replayed
        parsed = parse_create_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        if trusted_local_mode_enabled(self.settings):
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

        response = (
            self.queue_cloud_run(
                create_queued_session(self.stores, parsed, host_context=host_context),
                idempotency_key=idempotency_key,
            )
            if parsed["execute"] and self.settings.deployment == "cloud"
            else self._create_and_execute_session(parsed)
            if parsed["execute"]
            else create_queued_session(self.stores, parsed, host_context=host_context)
        )
        if idempotency_key is None or response.status_code != 201:
            return response
        return save_idempotent_response(
            store=self.stores.idempotency,
            action="session.create",
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
        )

    def resume_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        parsed = parse_resume_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key

        claim_service = SessionClaimService(
            self.stores.leases,
            SessionRecoveryService(self.stores.events, self.stores.sessions),
        )
        try:
            result = SessionExecutionService(
                database_path=self.database_path,
                claim_service=claim_service,
                resume_service=SessionResumeService(claim_service),
                settings=self.settings,
                stores=self.stores,
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
            },
        )

    def cancel_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return cancel_session_control(
            self.database_path, str(session_key), payload, stores=self.stores
        )

    def suspend_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return suspend_session_control(
            self.database_path, str(session_key), payload, stores=self.stores
        )

    def append_session_message(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        parsed = parse_append_session_message_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed

        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key

        projection_store = self.stores.sessions
        session = projection_store.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        try:
            event = SessionMessageAppendService().build_event(
                session=session,
                next_sequence=session.current_sequence + 1,
                command=SessionMessageAppendCommand(
                    content=parsed["content"],
                    clarification_id=parsed["clarification_id"],
                ),
            )
        except ValueError as exc:
            return conflict(
                session_id=session_id,
                status="not_appendable",
                reason=(
                    "cannot_append_to_terminal_session"
                    if "terminal session" in str(exc)
                    else str(exc)
                ),
            )
        attachment_refs = store_text_attachments(
            self.stores.artifact_payloads,
            session_id=session_key,
            message_event=event,
            attachments=parsed["attachments"],
            created_at=event.created_at,
        )
        event = attach_refs_to_user_event(event, attachment_refs)
        self.stores.events.append(event)
        updated_session = projection_store.save_session(apply_event(session, event))
        body: dict[str, object] = {
            "session_id": session_id,
            "appended": True,
            **(
                {
                    "clarification_resolved": True,
                    "clarification_id": parsed["clarification_id"],
                }
                if event.event_type.value == "clarification_responded"
                else {}
            ),
            "content": parsed["content"],
            "sequence": event.sequence,
            "status": updated_session.status.value,
            "current_sequence": updated_session.current_sequence,
        }
        if attachment_refs:
            body["attachments"] = [ref.to_mapping() for ref in attachment_refs]
        return ApiResponse(
            status_code=201,
            body=body,
        )

    def _create_and_execute_session(self, parsed: CreateSessionPayload) -> ApiResponse:
        workspace_root = Path(str(parsed["workspace"])).expanduser().resolve()
        confirmed_memories = list_confirmed_repo_memories(
            self.stores.memories,
            repo_id=str(workspace_root),
        )
        try:
            model_gateway = build_model_gateway(_model_provider_settings(self.settings))
        except ValueError as error:
            return service_unavailable(
                status="model_gateway_unavailable",
                reason=str(error),
            )
        try:
            trusted_local = trusted_local_mode_enabled(self.settings)
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
                web_search_endpoint=self.settings.web_search_endpoint,
                skill_roots=scoped_skill_roots(self.settings),
                skills_state=runtime_skills_state(self.settings),
                mcp_servers=self.settings.mcp_servers,
                mcp_allowlist=parsed["mcp_allowlist"],
                trusted_local=trusted_local,
                max_model_calls=parsed["max_model_calls"],
                max_tool_calls=parsed["max_tool_calls"],
                session_history=self.stores.session_history.scoped(parsed["history_session_ids"]),
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
            )
        except ValueError as error:
            return service_unavailable(
                status="tool_gateway_unavailable",
                reason=str(error),
            )
        events, attachment_refs = persist_initial_attachments(
            self.stores.artifact_payloads,
            tuple(result.events),
            parsed["attachments"],
        )
        for event in events:
            self.stores.events.append(event)
        self.stores.sessions.save_session(result.session)
        self.stores.workspaces.save_workspace(rebuild_workspace(list(events)))
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


def _model_provider_settings(settings: ZebraAgentSettings) -> ModelProviderSettings:
    model = settings.model
    return ModelProviderSettings(
        provider=model.provider,
        api_key_env=model.api_key_env,
        base_url=model.base_url,
        model=model.model,
        executor_profile=model.executor_profile,
        planner_profile=model.planner_profile,
        reviewer_profile=model.reviewer_profile,
        summarizer_profile=model.summarizer_profile,
        analyst_profile=model.analyst_profile,
        classifier_profile=model.classifier_profile,
        max_retries=model.max_retries,
        deepseek_beta_enabled=model.deepseek_beta_enabled,
        deepseek_beta_base_url=model.deepseek_beta_base_url,
    )
