from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from tempfile import gettempdir

from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.ports.runtime import RuntimeCapabilityError, RuntimeSnapshot
from agent_runtime import LocalRuntime
from agent_runtime.adapters.local_snapshot_state import LocalSnapshotStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore

from zebra_agent_worker.recovery import (
    RecoveredSession,
    SessionRecoveryError,
    SessionRecoveryService,
)


class SessionControlError(ValueError):
    """Raised when a control-plane runtime operation cannot be completed."""


@dataclass(frozen=True)
class SuspendedSession:
    event: SessionEvent
    workspace: WorkspaceProjection


@dataclass(frozen=True)
class CancelledSession:
    event: SessionEvent
    workspace: WorkspaceProjection


@dataclass(frozen=True)
class RestoredWorkspace:
    event: SessionEvent
    workspace: WorkspaceProjection


class SessionControlService:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._event_store = SQLiteEventStore(database_path)
        self._projection_store = SQLiteProjectionStore(database_path)
        self._workspace_store = SQLiteWorkspaceProjectionStore(database_path)
        self._recovery_service = SessionRecoveryService(
            self._event_store,
            self._projection_store,
            self._workspace_store,
        )

    def suspend_session(
        self,
        session_id: SessionId,
        *,
        suspended_at: datetime | None = None,
    ) -> SuspendedSession:
        recovery = self._recover(session_id)
        if recovery.session.status not in {
            SessionStatus.READY,
            SessionStatus.RUNNING,
            SessionStatus.WAITING_APPROVAL,
        }:
            raise SessionControlError("session cannot be suspended from its current state")
        if recovery.workspace.status is WorkspaceStatus.SUSPENDED:
            raise SessionControlError("workspace is already suspended")

        runtime = build_local_runtime(self._database_path)
        handle = runtime.provision(workspace_root=recovery.workspace.workspace_root)
        snapshot = runtime.snapshot(handle)
        if snapshot.snapshot_path is None:
            raise SessionControlError("local runtime did not return snapshot_path")

        event = SessionEvent.create(
            session_id=session_id,
            sequence=recovery.session.current_sequence + 1,
            event_type=EventType.SESSION_SUSPENDED,
            actor=EventActor.SYSTEM,
            payload={
                "runtime_name": snapshot.runtime_name,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_path": snapshot.snapshot_path,
            },
            created_at=suspended_at or datetime.now(UTC),
        )
        self._event_store.append(event)
        updated_session = apply_session_event(recovery.session, event)
        updated_workspace = apply_workspace_event(recovery.workspace, event)
        self._projection_store.save_session(updated_session)
        self._workspace_store.save_workspace(updated_workspace)
        return SuspendedSession(event=event, workspace=updated_workspace)

    def cancel_session(
        self,
        session_id: SessionId,
        *,
        cancelled_at: datetime | None = None,
    ) -> CancelledSession:
        recovery = self._recover(session_id)
        if recovery.session.status not in {
            SessionStatus.READY,
            SessionStatus.RUNNING,
            SessionStatus.WAITING_APPROVAL,
            SessionStatus.WAITING_INPUT,
            SessionStatus.SUSPENDED,
        }:
            raise SessionControlError("session cannot be cancelled from its current state")

        event = SessionEvent.create(
            session_id=session_id,
            sequence=recovery.session.current_sequence + 1,
            event_type=EventType.SESSION_CANCELLED,
            actor=EventActor.SYSTEM,
            created_at=cancelled_at or datetime.now(UTC),
        )
        self._event_store.append(event)
        updated_session = apply_session_event(recovery.session, event)
        updated_workspace = apply_workspace_event(recovery.workspace, event)
        self._projection_store.save_session(updated_session)
        self._workspace_store.save_workspace(updated_workspace)
        return CancelledSession(event=event, workspace=updated_workspace)

    def restore_suspended_workspace(
        self,
        session_id: SessionId,
        *,
        resumed_at: datetime | None = None,
    ) -> RestoredWorkspace | None:
        recovery = self._recover(session_id)
        if recovery.session.status is not SessionStatus.SUSPENDED:
            return None
        workspace = recovery.workspace
        if workspace.status is not WorkspaceStatus.SUSPENDED:
            raise SessionControlError("workspace projection is not suspended")
        if (
            workspace.runtime_name is None
            or workspace.snapshot_id is None
            or workspace.snapshot_path is None
        ):
            raise SessionControlError("suspended workspace is missing snapshot metadata")

        runtime = build_local_runtime(self._database_path)
        snapshot = RuntimeSnapshot(
            snapshot_id=workspace.snapshot_id,
            runtime_name=workspace.runtime_name,
            source_handle_id=workspace.snapshot_id,
            created_at=workspace.updated_at,
            workspace_root=workspace.workspace_root,
            snapshot_path=workspace.snapshot_path,
        )
        inspection = runtime.inspect_snapshot(snapshot)
        if inspection.status is LocalSnapshotStatus.MISSING:
            raise SessionControlError("suspended workspace snapshot payload is unavailable")
        if inspection.status is LocalSnapshotStatus.INCOMPATIBLE:
            raise SessionControlError("suspended workspace snapshot is incompatible")
        try:
            restored = runtime.restore(snapshot)
        except RuntimeCapabilityError as exc:
            raise SessionControlError(str(exc)) from exc
        if restored.workspace_root is None:
            raise SessionControlError("restored runtime did not return workspace_root")
        runtime.cleanup_snapshot(snapshot)

        event = SessionEvent.create(
            session_id=session_id,
            sequence=recovery.session.current_sequence + 1,
            event_type=EventType.SESSION_RESUMED,
            actor=EventActor.SYSTEM,
            payload={
                "runtime_name": workspace.runtime_name,
                "snapshot_id": workspace.snapshot_id,
                "workspace_root": restored.workspace_root,
            },
            created_at=resumed_at or datetime.now(UTC),
        )
        self._event_store.append(event)
        updated_session = apply_session_event(recovery.session, event)
        updated_workspace = apply_workspace_event(workspace, event)
        self._projection_store.save_session(updated_session)
        self._workspace_store.save_workspace(updated_workspace)
        return RestoredWorkspace(event=event, workspace=updated_workspace)

    def _recover(self, session_id: SessionId) -> RecoveredSession:
        try:
            return self._recovery_service.recover_session(session_id)
        except SessionRecoveryError as exc:
            raise SessionControlError("session was not found") from exc


def build_local_runtime(database_path: Path) -> LocalRuntime:
    database_key = sha1(str(database_path.resolve()).encode("utf-8")).hexdigest()[:12]
    runtime_root = Path(gettempdir()) / "zebra-agent-runtime" / database_key
    return LocalRuntime(snapshot_root=runtime_root)
