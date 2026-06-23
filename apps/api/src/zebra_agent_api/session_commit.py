from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_runtime import WorkspaceCommitCommand, WorkspaceCommitError, WorkspaceCommitService
from agent_security import CommitPolicy, DeliveryDecisionType
from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.idempotency import replay_idempotent_response, save_idempotent_response
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_policy_profile, session_workspace_root
from zebra_agent_api.session_payloads import parse_commit_session_payload


@dataclass(frozen=True)
class SessionCommitApi:
    database_path: Path

    def commit(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> ApiResponse:
        parsed = parse_commit_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        replayed = replay_idempotent_response(
            database_path=self.database_path,
            action="session.commit",
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
        policy_decision = CommitPolicy().evaluate(session_policy_profile(events))
        if policy_decision.decision is DeliveryDecisionType.DENY:
            return self._save(
                payload,
                idempotency_key,
                conflict(
                    session_id=session_id,
                    status="policy_blocked",
                    reason=policy_decision.reason,
                ),
            )
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return self._save(
                payload,
                idempotency_key,
                conflict(
                    session_id=session_id,
                    status="commit_unavailable",
                    reason="session workspace_root is unavailable",
                ),
            )
        try:
            result = WorkspaceCommitService().commit(
                workspace_root,
                WorkspaceCommitCommand(
                    message=parsed["message"],
                    author_name=parsed["author_name"],
                    author_email=parsed["author_email"],
                ),
            )
        except (ValueError, WorkspaceCommitError) as error:
            return self._save(
                payload,
                idempotency_key,
                conflict(
                    session_id=session_id,
                    status="commit_unavailable",
                    reason=str(error),
                ),
            )
        return self._save(
            payload,
            idempotency_key,
            ApiResponse(
                status_code=201,
                body={
                    "session_id": session_id,
                    "committed": True,
                    "commit_sha": result.commit_sha,
                    "message": result.message,
                    "workspace": str(result.workspace_root),
                    "policy_profile": policy_decision.policy_profile,
                },
            ),
        )

    def _save(
        self,
        payload: dict[str, object],
        idempotency_key: str | None,
        response: ApiResponse,
    ) -> ApiResponse:
        return save_idempotent_response(
            database_path=self.database_path,
            action="session.commit",
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
        )
