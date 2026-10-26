from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.application import attach_refs_to_user_event
from agent_core.application.agent_definitions import PublisherGrantPort
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.ports import EffectStateReadPort, LiveEventFanoutPort
from agent_core.ports.agent_registry import AgentRegistryPort
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane
from agent_core.ports.task_schedules import TaskScheduleFiringStorePort, TaskScheduleStorePort
from agent_integrations import (
    GitHubPullRequestTransport,
    build_model_gateway,
)
from agent_integrations.redis_live_fanout_async import AsyncRedisNotifications
from agent_runtime import (
    read_mcp_resource_attachments,
    validate_mcp_capability_selection,
)
from agent_security import (
    CredentialBroker,
)
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import (
    ControlPlaneStores,
    store_text_attachments,
)
from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
from agent_storage.postgres.direct_control import PostgresDirectControl
from zebra_agent_config import (
    ZebraAgentSettings,
    trusted_local_mode_enabled,
)

from zebra_agent_api.agent_definition_binding import resolve_definition_binding
from zebra_agent_api.agent_definitions import ApiAgentDefinitionsMixin
from zebra_agent_api.agent_release_api import ApiAgentReleaseMixin
from zebra_agent_api.api_approval_control_mixin import ApiApprovalControlMixin
from zebra_agent_api.api_artifact_read_mixin import ApiArtifactReadMixin
from zebra_agent_api.api_command_mixin import ApiCommandMixin
from zebra_agent_api.api_memory_control_mixin import ApiMemoryControlMixin
from zebra_agent_api.api_memory_read_mixin import ApiMemoryReadMixin
from zebra_agent_api.api_personalization_mixin import ApiPersonalizationMixin
from zebra_agent_api.api_scm_mixin import ApiScmMixin
from zebra_agent_api.api_session_handoff_mixin import ApiSessionHandoffMixin
from zebra_agent_api.api_session_read_mixin import ApiSessionReadMixin
from zebra_agent_api.api_status_mixin import ApiStatusMixin
from zebra_agent_api.api_workspace_mixin import (
    WorkspaceApiMixin,
    WorkspaceControlStorePort,
)
from zebra_agent_api.coverage_http_admission import CoverageHttpAdmission, create_strict_session
from zebra_agent_api.factory import create_app as create_app
from zebra_agent_api.idempotency import replay_idempotent_response
from zebra_agent_api.platform_operator_auth import PlatformOperatorAuthorizer
from zebra_agent_api.responses import ApiResponse, bad_request, conflict
from zebra_agent_api.serialization import serialize_trace_events
from zebra_agent_api.session_binding import (
    _compose_admission,
    _post_admission_idempotency,
)
from zebra_agent_api.session_control import ApiSessionControlMixin
from zebra_agent_api.session_identity_read import _parse_session_id as parse_session_id
from zebra_agent_api.session_message_submission import (
    append_session_message_event,
    build_session_message_event,
    message_sequence_conflict,
)
from zebra_agent_api.session_payloads import (
    CreateSessionPayload,
    parse_append_session_message_payload,
    parse_create_session_payload,
    parse_resume_session_payload,
)
from zebra_agent_api.session_prompt_inputs import resolve_mcp_prompt_attachment
from zebra_agent_api.session_queue import create_queued_session
from zebra_agent_api.session_replay import reconcile_replayed_run
from zebra_agent_api.skills_admin import (
    ApiSkillsAdminMixin,
)
from zebra_agent_api.storage_composition import ControlPlaneStorageMixin
from zebra_agent_api.stream_v2_reader import StreamV2Reader
from zebra_agent_api.usage_api import UsageEvidenceReader


@dataclass(frozen=True)
class ZebraAgentApi(
    ControlPlaneStorageMixin,
    ApiStatusMixin,
    ApiCommandMixin,
    ApiSessionControlMixin,
    ApiSessionReadMixin,
    ApiSessionHandoffMixin,
    ApiMemoryReadMixin,
    ApiArtifactReadMixin,
    ApiMemoryControlMixin,
    ApiPersonalizationMixin,
    ApiScmMixin,
    ApiApprovalControlMixin,
    ApiSkillsAdminMixin,
    WorkspaceApiMixin,
    ApiAgentDefinitionsMixin,
    ApiAgentReleaseMixin,
):
    database_path: Path
    settings: ZebraAgentSettings
    _stores: ControlPlaneStores | None = None
    cloud_control: PostgresDirectControl | None = None
    command_outcome: PostgresCommandOutcomeReader | None = None
    live_event_fanout: LiveEventFanoutPort | None = None
    stream_notifications: AsyncRedisNotifications | None = None
    stream_v2_reader: StreamV2Reader | None = None
    effect_state: EffectStateReadPort | None = None
    workspace_control_store: WorkspaceControlStorePort | None = None
    administrative_context_namespace: str | None = None
    credential_broker: CredentialBroker | None = None
    github_transport: GitHubPullRequestTransport | None = None
    agent_registry: AgentRegistryPort | None = None
    publisher_grants: PublisherGrantPort | None = None
    publication_security_revocation_actors: frozenset[str] = frozenset()
    client_platform: AgentPlatformControlPlane | None = None
    platform_operator_authorizer: PlatformOperatorAuthorizer | None = None
    task_schedule_store: TaskScheduleStorePort | None = None
    task_schedule_firing_store: TaskScheduleFiringStorePort | None = None
    usage_evidence: UsageEvidenceReader | None = None
    coverage_http_admission: CoverageHttpAdmission | None = None
    _parse_session_id = staticmethod(parse_session_id)

    def create_session(
        self,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
        host_context: HostContextEnvelope | None = None,
        verified_host_grant: VerifiedHostGrant | None = None,
    ) -> ApiResponse:
        from zebra_agent_api.idempotency import scoped_idempotency_key

        if "coverage_admission" in payload:
            return create_strict_session(
                self,
                payload,
                idempotency_key=idempotency_key,
                host_context=host_context,
                verified_host_grant=verified_host_grant,
            )

        storage_idempotency_key = scoped_idempotency_key(idempotency_key, host_context)
        replayed = (
            replay_idempotent_response(
                store=self.stores.idempotency,
                action="session.create",
                idempotency_key=storage_idempotency_key,
                payload=payload,
            )
            if storage_idempotency_key is not None
            else None
        )
        if replayed is not None:
            return reconcile_replayed_run(self, replayed, payload, idempotency_key)
        parsed = parse_create_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        workspace_source = parsed.get("workspace_source")
        if workspace_source is not None:
            from uuid import uuid4 as _uuid4

            from agent_core.domain.workspace_control import WorkspaceId as _WorkspaceId

            if self.workspace_control_store is None:
                return bad_request("workspace_source requires the cloud workspace control plane")
            workspace_id = _WorkspaceId(_uuid4())
            self.workspace_control_store.create_pending(
                workspace_source,
                workspace_id=workspace_id,
                quota_bytes=256 * 1024 * 1024,
                owner_session_id=None,
                idempotency_key=(f"session-workspace:{idempotency_key or workspace_id}"),
            )
            parsed["workspace"] = f"workspace://{workspace_id}"
        if trusted_local_mode_enabled(self.settings):
            parsed["network_profile"] = "full-trusted-local"
            parsed["network_allowlist"] = []
        definition_snapshot = resolve_definition_binding(
            self.agent_registry,
            self.publisher_grants,
            parsed,
            host_context=host_context,
            settings=self.settings,
            verified_host_grant=verified_host_grant,
        )
        if isinstance(definition_snapshot, ApiResponse):
            return definition_snapshot
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

        admission = _compose_admission(self, host_context, payload, storage_idempotency_key)
        if isinstance(admission, ApiResponse):
            return admission
        admission_kwargs: dict[str, str] = admission  # type: ignore[assignment]

        def _queued() -> ApiResponse:
            return create_queued_session(
                self.stores,
                parsed,
                host_context=host_context,
                definition_snapshot=definition_snapshot,
                verified_host_grant=verified_host_grant,
                **admission_kwargs,
            )

        response = (
            self.queue_cloud_run(_queued(), idempotency_key=storage_idempotency_key)
            if parsed["execute"] and self.settings.deployment == "cloud"
            else self._create_and_execute_session(parsed)
            if parsed["execute"]
            else _queued()
        )
        result = _post_admission_idempotency(
            self.settings,
            self.stores,
            storage_idempotency_key,
            response,
            payload,
            public_idempotency_key=idempotency_key,
        )
        return result if isinstance(result, ApiResponse) else response

    def resume_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        parsed = parse_resume_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key

        from zebra_agent_api.local_execution import (
            LeaseConflictError,
            SessionClaimService,
            SessionExecutionService,
            SessionRecoveryError,
            SessionRecoveryService,
            SessionResumeError,
            SessionResumeService,
            WorkerExecutionError,
        )

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
        except (
            SessionRecoveryError,
            SessionResumeError,
            LeaseConflictError,
            WorkerExecutionError,
            ValueError,
        ) as error:
            from zebra_agent_api.local_execution import (  # noqa: PLC0415
                map_execution_error,
            )

            mapped = map_execution_error(session_id, error)
            if mapped is not None:
                return mapped
            raise
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

    def append_session_message(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        include_message_coordinates: bool = False,
    ) -> ApiResponse:
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
            event = build_session_message_event(
                event_store=self.stores.events,
                session=session,
                content=parsed["content"],
                clarification_id=parsed["clarification_id"],
                model_profile=parsed["model_profile"],
                reasoning_effort=parsed["reasoning_effort"],
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
        stored = append_session_message_event(self.stores.events, event)
        if stored is None:
            return message_sequence_conflict(session_id)
        event = stored
        updated_session = projection_store.save_session(apply_event(session, event))
        workspace = self.stores.workspaces.get_workspace(session_key)
        if workspace is not None:
            self.stores.workspaces.save_workspace(apply_workspace_event(workspace, event))
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
        if include_message_coordinates:
            body["message_coordinates"] = {
                "event_id": str(event.event_id),
                "segment_id": str(event.session_id),
                "segment_sequence": event.sequence,
            }
        if attachment_refs:
            body["attachments"] = [ref.to_mapping() for ref in attachment_refs]
        return ApiResponse(
            status_code=201,
            body=body,
        )

    def _create_and_execute_session(self, parsed: CreateSessionPayload) -> ApiResponse:
        from zebra_agent_api.local_execution import create_and_execute_session

        return create_and_execute_session(self, parsed, build_model_gateway)
