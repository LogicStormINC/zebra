"""Registry port for client sessions, mounted snapshots and run bindings."""

from datetime import datetime
from typing import Protocol

from agent_core.domain.client_capabilities import MountedCapabilitySnapshot
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import ClientSession
from agent_core.domain.identifiers import ClientSessionId, TaskId


class ClientSessionRegistryPort(Protocol):
    def create_session(self, session: ClientSession) -> None: ...

    def get_session(self, session_id: ClientSessionId) -> ClientSession | None: ...

    def heartbeat_session(
        self, session_id: ClientSessionId, *, heartbeat_at: datetime
    ) -> ClientSession:
        """Expired sessions refuse renewal (fail closed)."""

    def close_session(self, session_id: ClientSessionId) -> None: ...

    def save_mounted_snapshot(self, snapshot: MountedCapabilitySnapshot) -> None: ...

    def get_mounted_snapshot(
        self, client_session_id: ClientSessionId
    ) -> MountedCapabilitySnapshot | None: ...

    def save_run_binding(self, binding: ClientRunBinding) -> None:
        """Idempotent on the binding key; revisions only increase."""

    def get_run_binding(
        self, task_id: TaskId, run_id: str, client_session_id: ClientSessionId
    ) -> ClientRunBinding | None: ...
