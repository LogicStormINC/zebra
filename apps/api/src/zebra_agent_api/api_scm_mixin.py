from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_integrations import GitHubPullRequestTransport, build_pull_request_gateway
from agent_security import CredentialBroker
from agent_storage import ControlPlaneStores
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_commit import SessionCommitApi
from zebra_agent_api.session_pull_request import SessionPullRequestApi


class ApiScmMixin:
    database_path: Path
    stores: ControlPlaneStores
    settings: ZebraAgentSettings
    credential_broker: CredentialBroker | None
    github_transport: GitHubPullRequestTransport | None
    _parse_session_id: Callable[[str], SessionId | ApiResponse]

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
        return SessionCommitApi(self.database_path, self.stores).commit(
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
            self.stores,
            pull_request_gateway=gateway,
        ).open_pull_request(
            str(session_key),
            payload,
            idempotency_key=idempotency_key,
        )
