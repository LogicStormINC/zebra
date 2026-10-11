from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import ControlPlaneStores
from agent_storage.postgres.task_io import task_io_deadline

from zebra_agent_api.approval_read import ApprovalReadApi
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_context_control import SessionContextControlApi
from zebra_agent_api.session_list import SessionListApi
from zebra_agent_api.session_read import SessionReadApi
from zebra_agent_api.tenant_guard import (
    _task_principal_response,
    host_list_context_response,
    scope_session_list_response,
)


class ApiSessionReadMixin:
    database_path: Path
    stores: ControlPlaneStores
    administrative_context_namespace: str | None

    def get_session(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session(session_id)

    def list_sessions(
        self,
        query: Mapping[str, str],
        *,
        host_context: HostContextEnvelope | None = None,
        verified_host_grant: VerifiedHostGrant | None = None,
        include_tasks: bool = False,
    ) -> ApiResponse:
        if host_context is not None and getattr(self.stores, "deployment_namespace", None):
            return self._authorized_list_response(
                host_context,
                verified_host_grant,
                lambda authorize: SessionListApi(self.stores).list_sessions(
                    query,
                    authorize_task=authorize,
                    include_tasks=include_tasks,
                ),
            )
        response = SessionListApi(self.stores).list_sessions(query)
        return scope_session_list_response(self.stores.sessions, response, host_context)

    def list_approvals(
        self,
        *,
        host_context: HostContextEnvelope | None = None,
        verified_host_grant: VerifiedHostGrant | None = None,
    ) -> ApiResponse:
        if host_context is not None and getattr(self.stores, "deployment_namespace", None):
            return self._authorized_list_response(
                host_context,
                verified_host_grant,
                lambda authorize: ApprovalReadApi(self.stores).list_approvals(
                    authorize_task=authorize
                ),
            )
        response = ApprovalReadApi(self.stores).list_approvals()
        return scope_session_list_response(self.stores.sessions, response, host_context)

    def _authorized_list_response(
        self,
        context: HostContextEnvelope,
        verified: VerifiedHostGrant | None,
        operation: Callable[[Callable[[TaskId], ApiResponse | None]], ApiResponse],
    ) -> ApiResponse:
        denied = host_list_context_response(context, verified)
        if denied is not None:
            return denied
        assert verified is not None and context.expires_at is not None
        runs = [ref.resource_id for ref in context.resource_refs if ref.resource_type == "run"]
        deadline = monotonic() + min(2.0, (context.expires_at - datetime.now(UTC)).total_seconds())
        try:
            with task_io_deadline(deadline):
                response = operation(
                    lambda task_id: _task_principal_response(
                        self,
                        str(task_id),
                        context,
                        authority_issuer=verified.authority_issuer,
                        run_id=runs[0] if runs else None,
                    )
                )
        except CheckpointNotReady:
            return host_list_context_response(context, verified) or ApiResponse(
                409,
                {"status": "projection_not_ready", "retryable": True},
            )
        except Exception:
            return host_list_context_response(context, verified) or ApiResponse(
                503,
                {"status": "resource_list_unavailable"},
            )
        return host_list_context_response(context, verified) or (
            ApiResponse(403, {"status": "host_grant_rejected"})
            if datetime.now(UTC) >= context.expires_at
            else response
        )

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
