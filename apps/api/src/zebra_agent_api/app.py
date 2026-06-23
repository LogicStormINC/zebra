from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.application import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
    SessionBootstrapCommand,
    SessionBootstrapService,
    SessionMessageAppendCommand,
    SessionMessageAppendService,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.identifiers import SessionId
from agent_core.harness.models import HarnessLoopResult
from agent_integrations import (
    GitHubPullRequestTransport,
    build_model_gateway,
    build_pull_request_gateway,
)
from agent_runtime import run_local_harness
from agent_security import CredentialBroker, PolicyProfile
from agent_storage import (
    LeaseConflictError,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
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

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.serialization import serialize_trace_events
from zebra_agent_api.session_commit import SessionCommitApi
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

    def get_session_stream(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_stream(session_id)

    def get_session_diff(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_diff(session_id)

    def get_session_artifacts(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_artifacts(session_id)

    def get_session_delivery_audit(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path).get_session_delivery_audit(session_id)

    def commit_session(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> ApiResponse:
        return SessionCommitApi(self.database_path).commit(
            session_id,
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
            session_id,
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
                SessionId(UUID(session_id)),
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

    def append_session_message(self, session_id: str, payload: dict[str, object]) -> ApiResponse:
        parsed = parse_append_session_message_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed

        session_key = SessionId(UUID(session_id))
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
                command=SessionMessageAppendCommand(content=parsed["content"]),
            )
        except ValueError:
            return conflict(
                session_id=session_id,
                status="not_appendable",
                reason="cannot_append_to_terminal_session",
            )
        SQLiteEventStore(self.database_path).append(event)
        updated_session = projection_store.save_session(apply_event(session, event))
        return ApiResponse(
            status_code=201,
            body={
                "session_id": session_id,
                "appended": True,
                "content": parsed["content"],
                "sequence": event.sequence,
                "status": updated_session.status.value,
                "current_sequence": updated_session.current_sequence,
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
            )
        )
        event_store = SQLiteEventStore(self.database_path)
        for event in bootstrap.events:
            event_store.append(event)
        SQLiteProjectionStore(self.database_path).save_session(bootstrap.session)
        return ApiResponse(
            status_code=201,
            body={
                "session_id": str(bootstrap.session.session_id),
                "title": str(parsed["title"]),
                "prompt": str(parsed["prompt"]),
                "workspace": str(parsed["workspace"]),
                "executed": False,
                "status": bootstrap.session.status.value,
            },
        )

    def _create_and_execute_session(self, parsed: CreateSessionPayload) -> ApiResponse:
        workspace_root = Path(str(parsed["workspace"])).expanduser().resolve()
        result = run_local_harness(
            prompt=str(parsed["prompt"]),
            title=str(parsed["title"]),
            workspace_root=workspace_root,
            model_gateway=build_model_gateway(self.settings),
            policy_profile=PolicyProfile(str(parsed["policy_profile"])),
        )
        event_store = SQLiteEventStore(self.database_path)
        for event in result.events:
            event_store.append(event)
        SQLiteProjectionStore(self.database_path).save_session(result.session)
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

        session_key = SessionId(UUID(approval_id))
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
        SQLiteEventStore(self.database_path).append(event)
        updated_session = projection_store.save_session(apply_event(session, event))
        return ApiResponse(
            status_code=200,
            body={
                "approval_id": approval_id,
                "session_id": approval_id,
                "decision": decision,
                "event_type": event.event_type.value,
                "sequence": event.sequence,
                "status": updated_session.status.value,
            },
        )


def create_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    credential_broker: CredentialBroker | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
) -> ZebraAgentApi:
    active_settings = settings or load_settings()
    return ZebraAgentApi(
        database_path=Path(database_path or active_settings.database_url),
        settings=active_settings,
        credential_broker=credential_broker,
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
                }
                for tool in attempt.tools
            ],
        }
        for attempt in trace.attempts
    ]
