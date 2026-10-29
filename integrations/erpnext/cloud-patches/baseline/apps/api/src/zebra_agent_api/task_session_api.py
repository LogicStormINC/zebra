from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse


class TaskSessionApi(Protocol):
    @property
    def database_path(self) -> Path: ...

    @property
    def stores(self) -> ControlPlaneStores: ...

    def create_session(
        self,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
        host_context: HostContextEnvelope | None = None,
        verified_host_grant: VerifiedHostGrant | None = None,
    ) -> ApiResponse: ...

    def append_session_message(
        self, session_id: str, payload: dict[str, object]
    ) -> ApiResponse: ...

    def cancel_session(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        host_context: HostContextEnvelope | None = None,
        idempotency_key: str | None = None,
        task_id: TaskId | None = None,
    ) -> ApiResponse: ...

    def suspend_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse: ...

    def resume_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse: ...
