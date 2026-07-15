from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.application import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
    MemoryReviewAction,
    SessionBootstrapCommand,
    SessionBootstrapService,
    SessionMessageAppendCommand,
    SessionMessageAppendService,
)
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.identifiers import SessionId
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.harness.models import HarnessLoopResult
from agent_integrations import (
    GitHubPullRequestTransport,
    build_model_gateway,
    build_pull_request_gateway,
)
from agent_runtime import run_local_harness
from agent_security import CredentialBroker, PolicyProfile, parse_network_profile
from agent_storage import (
    LeaseConflictError,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    list_confirmed_repo_memories,
)
from zebra_agent_config import ZebraAgentSettings, load_settings
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryError,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
    WorkerExecutionError,
)

from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.approval_read import ApprovalReadApi
from zebra_agent_api.credential_broker import build_default_credential_broker
from zebra_agent_api.responses import ApiResponse, conflict, service_unavailable
from zebra_agent_api.serialization import serialize_trace_events
from zebra_agent_api.session_artifact_control import SessionArtifactControlApi
from zebra_agent_api.session_commit import SessionCommitApi
from zebra_agent_api.session_control import cancel_session_control, suspend_session_control
from zebra_agent_api.session_list import SessionListApi
from zebra_agent_api.session_memory_control import (
    preview_session_memory_queue,
    preview_tenant_memory_queue,
    preview_user_memory_queue,
    review_session_memory,
    review_session_memory_bulk,
    review_session_memory_queue,
    review_tenant_memory,
    review_tenant_memory_bulk,
    review_tenant_memory_queue,
    review_user_memory,
    review_user_memory_bulk,
    review_user_memory_queue,
)
from zebra_agent_api.session_payloads import (
    CreateSessionPayload,
    parse_append_session_message_payload,
    parse_approval_decision_payload,
    parse_create_session_payload,
    parse_resume_session_payload,
)
from zebra_agent_api.session_pull_request import SessionPullRequestApi
from zebra_agent_api.session_read import SessionReadApi


@dataclass(frozen=True)
class ZebraAgentApi:
    database_path: Path
    settings: ZebraAgentSettings
    credential_broker: CredentialBroker | None = None
    github_transport: GitHubPullRequestTransport | None = None

    def health(self) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "status": "ok",
                "service": "zebra-agent-api",
            },
        )

    def get_session(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session(session_id)

    def list_sessions(self, query: Mapping[str, str]) -> ApiResponse:
        return SessionListApi(self.database_path).list_sessions(query)

    def list_approvals(self) -> ApiResponse:
        return ApprovalReadApi(self.database_path).list_approvals()

    def get_approval(self, approval_id: str) -> ApiResponse:
        return ApprovalReadApi(self.database_path).get_approval(approval_id)

    def get_session_stream(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_stream(session_id)

    def get_session_diff(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_diff(session_id)

    def get_session_memory(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_memory(session_id)

    def get_session_memory_queue(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_memory_queue(session_id)

    def get_session_memory_queue_summary(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_memory_queue_summary(session_id)

    def get_memory_operations_overview(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_operations_overview(
            session_id,
            payload,
        )

    def get_memory_review_governance_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_review_governance_signals(
            session_id,
            payload,
        )

    def get_memory_backlog_aging_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_backlog_aging_signals(
            session_id,
            payload,
        )

    def get_memory_review_velocity_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_review_velocity_signals(
            session_id,
            payload,
        )

    def get_memory_backlog_pressure_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_backlog_pressure_signals(
            session_id,
            payload,
        )

    def get_memory_pressure_action_hints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_pressure_action_hints(
            session_id,
            payload,
        )

    def get_memory_pressure_escalation_recommendations(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_pressure_escalation_recommendations(
            session_id,
            payload,
        )

    def get_memory_escalation_follow_up_windows(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_escalation_follow_up_windows(
            session_id,
            payload,
        )

    def get_memory_follow_up_overdue_flags(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_follow_up_overdue_flags(
            session_id,
            payload,
        )

    def get_memory_overdue_age_buckets(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_age_buckets(
            session_id,
            payload,
        )

    def get_memory_overdue_type_rollups(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_type_rollups(
            session_id,
            payload,
        )

    def get_memory_overdue_visibility_rollups(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_visibility_rollups(
            session_id,
            payload,
        )

    def get_memory_overdue_trend_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_trend_signals(
            session_id,
            payload,
        )

    def get_memory_overdue_intervention_hints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_intervention_hints(
            session_id,
            payload,
        )

    def get_memory_overdue_escalation_lanes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_escalation_lanes(
            session_id,
            payload,
        )

    def get_memory_overdue_recovery_paths(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_recovery_paths(
            session_id,
            payload,
        )

    def get_memory_overdue_resolution_checkpoints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_resolution_checkpoints(
            session_id,
            payload,
        )

    def get_memory_overdue_resolution_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_resolution_outcomes(
            session_id,
            payload,
        )

    def get_memory_overdue_closure_decisions(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_closure_decisions(
            session_id,
            payload,
        )

    def get_memory_overdue_archive_recommendations(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_archive_recommendations(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_guidance(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_retention_guidance(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_windows(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_retention_windows(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breaches(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_retention_breaches(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_aging(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_retention_breach_aging(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_actions(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_retention_breach_actions(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_lanes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_retention_breach_lanes(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_owner_targets(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path).get_memory_overdue_retention_breach_owner_targets(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_modes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path
        ).get_memory_overdue_retention_breach_follow_through_modes(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path
        ).get_memory_overdue_retention_breach_follow_through_outcomes(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_completion_states(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path
        ).get_memory_overdue_retention_breach_follow_through_completion_states(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_verification_states(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path
        ).get_memory_overdue_retention_breach_follow_through_verification_states(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_verification_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path
        ).get_memory_overdue_retention_breach_follow_through_verification_outcomes(
            session_id,
            payload,
        )

    def get_user_memory(self, user_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_user_memory(user_id)

    def get_user_memory_queue(self, user_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_user_memory_queue(user_id)

    def get_user_memory_queue_summary(self, user_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_user_memory_queue_summary(user_id)

    def get_tenant_memory(self, tenant_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_tenant_memory(tenant_id)

    def get_tenant_memory_queue(self, tenant_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_tenant_memory_queue(tenant_id)

    def get_tenant_memory_queue_summary(self, tenant_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_tenant_memory_queue_summary(tenant_id)

    def get_session_artifacts(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_artifacts(session_id)

    def get_session_artifact_detail(self, session_id: str, artifact_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_artifact_detail(
            session_id,
            artifact_id,
        )

    def get_session_artifact_content(self, session_id: str, artifact_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_artifact_content(
            session_id,
            artifact_id,
        )

    def prune_session_artifact(self, session_id: str, artifact_id: str) -> ApiResponse:
        return SessionArtifactControlApi(self.database_path).prune_artifact(
            session_id,
            artifact_id,
        )

    def get_session_delivery_audit(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_delivery_audit(session_id)

    def confirm_session_memory(
        self,
        session_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory(
            database_path=self.database_path,
            session_id=session_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.CONFIRM,
            decision="confirm",
        )

    def expire_session_memory(
        self,
        session_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory(
            database_path=self.database_path,
            session_id=session_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.EXPIRE,
            decision="expire",
        )

    def bulk_review_session_memory(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory_bulk(
            database_path=self.database_path,
            session_id=session_id,
            payload=payload,
        )

    def review_session_memory_queue(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory_queue(
            database_path=self.database_path,
            session_id=session_id,
            payload=payload,
        )

    def preview_session_memory_queue(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return preview_session_memory_queue(
            database_path=self.database_path,
            session_id=session_id,
            payload=payload,
        )

    def confirm_user_memory(
        self,
        user_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory(
            database_path=self.database_path,
            user_id=user_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.CONFIRM,
            decision="confirm",
        )

    def expire_user_memory(
        self,
        user_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory(
            database_path=self.database_path,
            user_id=user_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.EXPIRE,
            decision="expire",
        )

    def bulk_review_user_memory(
        self,
        user_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory_bulk(
            database_path=self.database_path,
            user_id=user_id,
            payload=payload,
        )

    def review_user_memory_queue(
        self,
        user_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory_queue(
            database_path=self.database_path,
            user_id=user_id,
            payload=payload,
        )

    def preview_user_memory_queue(
        self,
        user_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return preview_user_memory_queue(
            database_path=self.database_path,
            user_id=user_id,
            payload=payload,
        )

    def confirm_tenant_memory(
        self,
        tenant_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory(
            database_path=self.database_path,
            tenant_id=tenant_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.CONFIRM,
            decision="confirm",
        )

    def expire_tenant_memory(
        self,
        tenant_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory(
            database_path=self.database_path,
            tenant_id=tenant_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.EXPIRE,
            decision="expire",
        )

    def bulk_review_tenant_memory(
        self,
        tenant_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory_bulk(
            database_path=self.database_path,
            tenant_id=tenant_id,
            payload=payload,
        )

    def review_tenant_memory_queue(
        self,
        tenant_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory_queue(
            database_path=self.database_path,
            tenant_id=tenant_id,
            payload=payload,
        )

    def preview_tenant_memory_queue(
        self,
        tenant_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return preview_tenant_memory_queue(
            database_path=self.database_path,
            tenant_id=tenant_id,
            payload=payload,
        )

    def commit_session(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> ApiResponse:
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return SessionCommitApi(self.database_path).commit(
            str(session_key),
            payload,
            idempotency_key=idempotency_key,
        )

    def open_session_pull_request(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> ApiResponse:
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        try:
            gateway = build_pull_request_gateway(
                self.settings.scm,
                credential_broker=self.credential_broker,
                github_transport=self.github_transport,
            )
        except ValueError as error:
            return conflict(
                session_id=session_id,
                status="pull_request_unavailable",
                reason=str(error),
            )
        return SessionPullRequestApi(
            self.database_path,
            pull_request_gateway=gateway,
        ).open_pull_request(
            str(session_key),
            payload,
            idempotency_key=idempotency_key,
        )

    def create_session(self, payload: dict[str, object]) -> ApiResponse:
        parsed = parse_create_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed

        if not parsed["execute"]:
            return self._create_queued_session(parsed)
        return self._create_and_execute_session(parsed)

    def resume_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        parsed = parse_resume_session_payload(payload)
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
        return cancel_session_control(self.database_path, str(session_key), payload)

    def suspend_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return suspend_session_control(self.database_path, str(session_key), payload)

    def append_session_message(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        parsed = parse_append_session_message_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed

        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key

        projection_store = SQLiteProjectionStore(self.database_path)
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
        SQLiteEventStore(self.database_path).append(event)
        updated_session = projection_store.save_session(apply_event(session, event))
        return ApiResponse(
            status_code=201,
            body={
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
            },
        )

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

    def approve(self, approval_id: str, payload: dict[str, object]) -> ApiResponse:
        return self._record_approval_decision(
            approval_id,
            payload,
            action=ApprovalDecisionAction.GRANT,
            decision="approve",
        )

    def reject(self, approval_id: str, payload: dict[str, object]) -> ApiResponse:
        return self._record_approval_decision(
            approval_id,
            payload,
            action=ApprovalDecisionAction.REJECT,
            decision="reject",
        )

    def _create_queued_session(self, parsed: CreateSessionPayload) -> ApiResponse:
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title=str(parsed["title"]),
                user_input=str(parsed["prompt"]),
                workspace_root=Path(str(parsed["workspace"])).expanduser().resolve(),
                policy_profile=str(parsed["policy_profile"]),
                tool_profile=ToolProfile(str(parsed["tool_profile"])),
                network_profile=str(parsed["network_profile"]),
                network_allowlist=tuple(parsed["network_allowlist"]),
            )
        )
        event_store = SQLiteEventStore(self.database_path)
        for event in bootstrap.events:
            event_store.append(event)
        SQLiteProjectionStore(self.database_path).save_session(bootstrap.session)
        SQLiteWorkspaceProjectionStore(self.database_path).save_workspace(
            rebuild_workspace(list(bootstrap.events))
        )
        return ApiResponse(
            status_code=201,
            body={
                "session_id": str(bootstrap.session.session_id),
                "title": str(parsed["title"]),
                "prompt": str(parsed["prompt"]),
                "workspace": str(parsed["workspace"]),
                "executed": False,
                "status": bootstrap.session.status.value,
                "tool_profile": str(parsed["tool_profile"]),
                "network_profile": str(parsed["network_profile"]),
                "network_allowlist": parsed["network_allowlist"],
            },
        )

    def _create_and_execute_session(self, parsed: CreateSessionPayload) -> ApiResponse:
        workspace_root = Path(str(parsed["workspace"])).expanduser().resolve()
        confirmed_memories = list_confirmed_repo_memories(
            self.database_path,
            repo_id=str(workspace_root),
        )
        try:
            model_gateway = build_model_gateway(self.settings)
        except ValueError as error:
            return service_unavailable(
                status="model_gateway_unavailable",
                reason=str(error),
            )
        result = run_local_harness(
            prompt=str(parsed["prompt"]),
            title=str(parsed["title"]),
            workspace_root=workspace_root,
            model_gateway=model_gateway,
            policy_profile=PolicyProfile(str(parsed["policy_profile"])),
            tool_profile=ToolProfile(str(parsed["tool_profile"])),
            network_profile=parse_network_profile(
                str(parsed["network_profile"]),
                domain_allowlist=parsed["network_allowlist"],
            ),
            confirmed_memories=confirmed_memories,
        )
        event_store = SQLiteEventStore(self.database_path)
        for event in result.events:
            event_store.append(event)
        SQLiteProjectionStore(self.database_path).save_session(result.session)
        SQLiteWorkspaceProjectionStore(self.database_path).save_workspace(
            rebuild_workspace(list(result.events))
        )
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
                "trace": _trace_payload(result),
            },
        )

    def _record_approval_decision(
        self,
        approval_id: str,
        payload: dict[str, object],
        *,
        action: ApprovalDecisionAction,
        decision: str,
    ) -> ApiResponse:
        parsed = parse_approval_decision_payload(
            payload,
            default_reason=f"{decision} via API",
        )
        if isinstance(parsed, ApiResponse):
            return parsed

        session_key = self._parse_session_id(approval_id)
        if isinstance(session_key, ApiResponse):
            return session_key

        projection_store = SQLiteProjectionStore(self.database_path)
        session = projection_store.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"approval_id": approval_id, "status": "not_found"},
            )
        try:
            event = ApprovalDecisionService().build_event(
                session=session,
                next_sequence=session.current_sequence + 1,
                command=ApprovalDecisionCommand(
                    action=action,
                    operator=parsed["operator"],
                    reason=parsed["reason"],
                ),
            )
        except ValueError as error:
            return conflict(
                session_id=approval_id,
                status="invalid_state",
                reason=str(error),
            )
        event_store = SQLiteEventStore(self.database_path)
        approval_context = serialize_approval_context(session.approval_context)
        event_store.append(event)
        updated_session = projection_store.save_session(apply_event(session, event))
        body: dict[str, object] = {
            "approval_id": approval_id,
            "session_id": approval_id,
            "decision": decision,
            "event_type": event.event_type.value,
            "sequence": event.sequence,
            "status": updated_session.status.value,
        }
        if approval_context is not None:
            body["approval_context"] = approval_context
        return ApiResponse(status_code=200, body=body)


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


def _trace_payload(result: HarnessLoopResult) -> list[dict[str, object]]:
    from agent_core.harness.projection import HarnessTraceProjector

    trace = HarnessTraceProjector().project(result)
    return [
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
                    "policy_route": tool.policy_route,
                    "policy_target": tool.policy_target,
                    "policy_network_profile": tool.policy_network_profile,
                    "policy_scope": list(tool.policy_scope),
                }
                for tool in attempt.tools
            ],
        }
        for attempt in trace.attempts
    ]
