from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent_storage import ControlPlaneStores

from zebra_agent_api.approval_read import ApprovalReadApi
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_context_control import SessionContextControlApi
from zebra_agent_api.session_list import SessionListApi
from zebra_agent_api.session_read import SessionReadApi


class ApiSessionReadMixin:
    database_path: Path
    stores: ControlPlaneStores
    administrative_context_namespace: str | None

    def get_session(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session(session_id)

    def list_sessions(self, query: Mapping[str, str]) -> ApiResponse:
        return SessionListApi(self.stores).list_sessions(query)

    def list_approvals(self) -> ApiResponse:
        return ApprovalReadApi(self.stores).list_approvals()

    def get_approval(self, approval_id: str) -> ApiResponse:
        return ApprovalReadApi(self.stores).get_approval(approval_id)

    def get_session_stream(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_stream(session_id)

    def get_session_diff(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_diff(session_id)

    def get_session_context(self, session_id: str) -> ApiResponse:
        return SessionContextControlApi(
            self.database_path,
            self.stores,
            administrative_context_namespace=self.administrative_context_namespace,
        ).inspect(session_id)

    def compact_session_context(
        self, session_id: str, body: Mapping[str, object] | None = None
    ) -> ApiResponse:
        return SessionContextControlApi(
            self.database_path,
            self.stores,
            administrative_context_namespace=self.administrative_context_namespace,
        ).compact(session_id, body or {})

    def recover_session_context(self, session_id: str, body: Mapping[str, object]) -> ApiResponse:
        return SessionContextControlApi(
            self.database_path,
            self.stores,
            administrative_context_namespace=self.administrative_context_namespace,
        ).recover(session_id, body)

    def get_session_memory(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_memory(session_id)

    def get_session_memory_queue(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_memory_queue(session_id)

    def get_session_memory_queue_summary(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_memory_queue_summary(
            session_id
        )
