from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_integrations import (
    LocalOnlyPullRequestGateway,
    PullRequestGateway,
    PullRequestRequest,
    ScmIntegrationError,
    ScmUnavailableError,
)
from agent_security import DeliveryDecisionType, PullRequestPolicy
from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.idempotency import replay_idempotent_response, save_idempotent_response
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_policy_profile, session_workspace_root
from zebra_agent_api.session_payloads import parse_pull_request_payload


@dataclass(frozen=True)
class SessionPullRequestApi:
    database_path: Path
    pull_request_gateway: PullRequestGateway = field(default_factory=LocalOnlyPullRequestGateway)

    def open_pull_request(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> ApiResponse:
        parsed = parse_pull_request_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        replayed = replay_idempotent_response(
            database_path=self.database_path,
            action="session.pull_request",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replayed is not None:
            return replayed

        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return self._save(
                payload,
                idempotency_key,
                ApiResponse(
                    status_code=404,
                    body={"session_id": session_id, "status": "not_found"},
                ),
            )
        events = SQLiteEventStore(self.database_path).list_for_session(session_key)
        policy_decision = PullRequestPolicy().evaluate(session_policy_profile(events))
        if policy_decision.decision is DeliveryDecisionType.DENY:
            return self._save(
                payload,
                idempotency_key,
                conflict(
                    session_id=session_id,
                    status="policy_blocked",
                    reason=policy_decision.reason,
                ),
                policy_profile=policy_decision.policy_profile,
            )
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return self._save(
                payload,
                idempotency_key,
                conflict(
                    session_id=session_id,
                    status="pull_request_unavailable",
                    reason="session workspace_root is unavailable",
                ),
                policy_profile=policy_decision.policy_profile,
            )
        try:
            plan = self.pull_request_gateway.plan(
                workspace_root,
                PullRequestRequest(
                    title=parsed["title"],
                    body=parsed["body"],
                    base_branch=parsed["base_branch"],
                    head_branch=parsed["head_branch"],
                    dry_run=parsed["dry_run"],
                ),
            )
        except ScmUnavailableError as error:
            return self._save(
                payload,
                idempotency_key,
                conflict(
                    session_id=session_id,
                    status="pull_request_unavailable",
                    reason=str(error),
                ),
                policy_profile=policy_decision.policy_profile,
            )
        except (ValueError, ScmIntegrationError) as error:
            return self._save(
                payload,
                idempotency_key,
                conflict(
                    session_id=session_id,
                    status="pull_request_unavailable",
                    reason=str(error),
                ),
                policy_profile=policy_decision.policy_profile,
            )
        return self._save(
            payload,
            idempotency_key,
            ApiResponse(
                status_code=200,
                body={
                    "session_id": session_id,
                    "pull_request": {
                        "provider": plan.provider,
                        "title": plan.title,
                        "body": plan.body,
                        "base_branch": plan.base_branch,
                        "head_branch": plan.head_branch,
                        "commit_sha": plan.commit_sha,
                        "dry_run": plan.dry_run,
                        "status": plan.status,
                        "url": plan.url,
                        "request_payload": plan.request_payload,
                    },
                    "policy_profile": policy_decision.policy_profile,
                },
            ),
            policy_profile=policy_decision.policy_profile,
        )

    def _save(
        self,
        payload: dict[str, object],
        idempotency_key: str | None,
        response: ApiResponse,
        *,
        policy_profile: str | None = None,
    ) -> ApiResponse:
        saved = save_idempotent_response(
            database_path=self.database_path,
            action="session.pull_request",
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
        )
        record_delivery_audit(
            database_path=self.database_path,
            session_id=str(saved.body["session_id"]),
            action="session.pull_request",
            response=saved,
            policy_profile=policy_profile,
            idempotency_key=idempotency_key,
        )
        return saved
