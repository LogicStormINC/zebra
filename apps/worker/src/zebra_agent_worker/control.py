from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import current_turn
from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeSnapshot,
    RuntimeSnapshotStatus,
)
from agent_storage import (
    ControlPlaneStores,
    PostgresControlPlaneStores,
    sqlite_control_plane_stores,
)
from agent_storage.postgres.direct_control import PostgresDirectControl
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_worker.recovery import (
    RecoveredSession,
    SessionRecoveryError,
    SessionRecoveryService,
)
from zebra_agent_worker.runtime_factory import build_runtime

# Control-plane admission includes AWAITING_TURN: a finished conversation
# Turn must still be cancellable/suspendable to establish hard boundaries
# (ADR-026 §2).
_CANCELLABLE_STATUSES = frozenset(
    {
        SessionStatus.READY,
        SessionStatus.RUNNING,
        SessionStatus.WAITING_APPROVAL,
        SessionStatus.WAITING_INPUT,
        SessionStatus.AWAITING_TURN,
        SessionStatus.SUSPENDED,
    }
)
_SUSPENDABLE_STATUSES = frozenset(
    {
        SessionStatus.READY,
        SessionStatus.RUNNING,
        SessionStatus.WAITING_APPROVAL,
        SessionStatus.AWAITING_TURN,
    }
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
    def __init__(
        self,
        database_path: Path,
        *,
        settings: ZebraAgentSettings | None = None,
        stores: ControlPlaneStores | PostgresControlPlaneStores | None = None,
        cloud_control: PostgresDirectControl | None = None,
    ) -> None:
        self._database_path = database_path
        self._settings = settings or load_settings()
        if stores is None and self._settings.storage_authority == "postgresql":
            raise SessionControlError("cloud direct control requires explicit stores")
        active_stores = stores or sqlite_control_plane_stores(database_path)
        self._cloud = (
            isinstance(active_stores, PostgresControlPlaneStores)
            or self._settings.storage_authority == "postgresql"
        )
        self._cloud_control = cloud_control
        if (
            cloud_control is not None
            and getattr(active_stores, "deployment_namespace", None)
            != cloud_control.deployment_namespace
        ):
            raise SessionControlError("cloud direct control composition does not match stores")
        self._event_store = active_stores.events
        self._projection_store = active_stores.sessions
        self._workspace_store = active_stores.workspaces
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
        if self._cloud:
            raise SessionControlError("cloud user suspend is unsupported")
        recovery = self._recover(session_id)
        if recovery.session.status not in _SUSPENDABLE_STATUSES:
            raise SessionControlError("session cannot be suspended from its current state")
        if recovery.workspace.status is WorkspaceStatus.SUSPENDED:
            raise SessionControlError("workspace is already suspended")

        handle = None
        try:
            runtime = build_runtime(
                self._settings,
                self._database_path,
                workspace_root=Path(recovery.workspace.workspace_root),
                network_profile=recovery.workspace.network_profile.value,
                session_id=str(session_id),
            )
            handle = runtime.provision(workspace_root=recovery.workspace.workspace_root)
            snapshot = runtime.snapshot(handle)
        except (RuntimeCapabilityError, ValueError) as exc:
            raise SessionControlError(str(exc)) from exc
        finally:
            if handle is not None:
                try:
                    runtime.destroy(handle)
                except RuntimeCapabilityError as exc:
                    raise SessionControlError(f"runtime cleanup failed: {exc}") from exc
        if snapshot.snapshot_path is None:
            raise SessionControlError("runtime did not return snapshot_path")

        session = recovery.session
        workspace = recovery.workspace
        authority = handle.authority
        if authority is not None:
            if (
                workspace.runtime_spec_digest is not None
                and workspace.runtime_spec_digest != authority.spec_digest
            ):
                runtime.cleanup_snapshot(snapshot)
                raise SessionControlError(
                    "configured runtime authority differs from session authority"
                )
            if workspace.runtime_spec_digest is None:
                authority_event = SessionEvent.create(
                    session_id=session_id,
                    sequence=session.current_sequence + 1,
                    event_type=EventType.RUNTIME_PROVISIONED,
                    actor=EventActor.SYSTEM,
                    payload={
                        "runtime_class": authority.runtime_class.value,
                        "engine": authority.engine,
                        "image": authority.image,
                        "spec_digest": authority.spec_digest,
                        "network_enforcement": authority.network_enforcement,
                        "workspace_writable": authority.workspace_writable,
                    },
                    created_at=suspended_at or datetime.now(UTC),
                )
                self._event_store.append(authority_event)
                session = apply_session_event(session, authority_event)
                workspace = apply_workspace_event(workspace, authority_event)
                self._projection_store.save_session(session)
                self._workspace_store.save_workspace(workspace)

        event = SessionEvent.create(
            session_id=session_id,
            sequence=session.current_sequence + 1,
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
        updated_session = apply_session_event(session, event)
        updated_workspace = apply_workspace_event(workspace, event)
        self._projection_store.save_session(updated_session)
        self._workspace_store.save_workspace(updated_workspace)
        return SuspendedSession(event=event, workspace=updated_workspace)

    def cancel_session(
        self,
        session_id: SessionId,
        *,
        cancelled_at: datetime | None = None,
        scope: OpaqueAuthorityScope | None = None,
        host_context: HostContextEnvelope | None = None,
        idempotency_key: str | None = None,
        operation_id: UUID | None = None,
        task_id: TaskId | None = None,
    ) -> CancelledSession:
        if self._cloud:
            if self._cloud_control is None:
                raise SessionControlError("cloud direct control requires explicit composition")
            try:
                if host_context is not None:
                    scope = self._cloud_control.host_scope(session_id, host_context)
                if scope is None:
                    raise ValueError("cloud direct control requires trusted caller scope")
                result = self._cloud_control.cancel(
                    session_id,
                    scope=scope,
                    host_context=host_context,
                    workspace_ref=None if host_context is None else host_context.workspace_ref,
                    idempotency_key=idempotency_key,
                    operation_id=operation_id,
                    task_id=task_id,
                )
                return CancelledSession(result.event, result.workspace)
            except ValueError as exc:
                raise SessionControlError(str(exc)) from exc
        recovery = self._recover(session_id)
        if recovery.session.status not in _CANCELLABLE_STATUSES:
            raise SessionControlError("session cannot be cancelled from its current state")

        try:
            runtime = build_runtime(
                self._settings,
                self._database_path,
                workspace_root=Path(recovery.workspace.workspace_root),
                network_profile=recovery.workspace.network_profile.value,
                session_id=str(session_id),
            )
            runtime.destroy_session(str(session_id))
        except (RuntimeCapabilityError, ValueError) as exc:
            raise SessionControlError(str(exc)) from exc

        for _ in range(64):
            recovery = self._recover(session_id)
            if recovery.session.status not in _CANCELLABLE_STATUSES:
                raise SessionControlError("session cannot be cancelled from its current state")
            open_turn = current_turn(self._event_store.list_for_session(session_id))
            next_sequence = recovery.session.current_sequence
            turn_cancel_event: SessionEvent | None = None
            try:
                if open_turn is not None:
                    # Close the executing Turn first so the durable stream
                    # records which interaction round was cancelled.
                    turn_cancel_event = SessionEvent.create(
                        session_id=session_id,
                        sequence=next_sequence + 1,
                        event_type=EventType.TURN_CANCELLED,
                        actor=EventActor.SYSTEM,
                        payload={
                            "turn_id": open_turn.turn_id,
                            "turn_index": open_turn.turn_index,
                            "reason": "session_cancelled",
                        },
                        idempotency_key=f"turn-cancel:{open_turn.turn_id}",
                        created_at=cancelled_at or datetime.now(UTC),
                    )
                    self._event_store.append(turn_cancel_event)
                    next_sequence += 1
                event = SessionEvent.create(
                    session_id=session_id,
                    sequence=next_sequence + 1,
                    event_type=EventType.SESSION_CANCELLED,
                    actor=EventActor.SYSTEM,
                    created_at=cancelled_at or datetime.now(UTC),
                )
                self._event_store.append(event)
                break
            except ValueError:
                # ponytail: bounded optimistic retry fits single-host SQLite; Phase B uses fencing.
                continue
        else:
            raise SessionControlError(
                "session cancellation could not win event sequence contention"
            )
        base_session = recovery.session
        base_workspace = recovery.workspace
        if turn_cancel_event is not None:
            base_session = apply_session_event(base_session, turn_cancel_event)
            base_workspace = apply_workspace_event(base_workspace, turn_cancel_event)
        updated_session = apply_session_event(base_session, event)
        updated_workspace = apply_workspace_event(base_workspace, event)
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

        snapshot = RuntimeSnapshot(
            snapshot_id=workspace.snapshot_id,
            runtime_name=workspace.runtime_name,
            source_handle_id=workspace.snapshot_id,
            created_at=workspace.updated_at,
            workspace_root=workspace.workspace_root,
            snapshot_path=workspace.snapshot_path,
            authority_digest=workspace.runtime_spec_digest,
            image=workspace.runtime_image,
        )
        try:
            runtime = build_runtime(
                self._settings,
                self._database_path,
                workspace_root=Path(workspace.workspace_root),
                network_profile=workspace.network_profile.value,
                session_id=str(session_id),
            )
            inspection = runtime.inspect_snapshot(snapshot)
        except (RuntimeCapabilityError, ValueError) as exc:
            raise SessionControlError(str(exc)) from exc
        if inspection.status is RuntimeSnapshotStatus.MISSING:
            raise SessionControlError("suspended workspace snapshot payload is unavailable")
        if inspection.status is RuntimeSnapshotStatus.INCOMPATIBLE:
            raise SessionControlError("suspended workspace snapshot is incompatible")
        restored = None
        try:
            restored = runtime.restore(snapshot)
            if restored.workspace_root is None:
                raise SessionControlError("restored runtime did not return workspace_root")
            restored_workspace_root = restored.workspace_root
        except (RuntimeCapabilityError, ValueError) as exc:
            raise SessionControlError(str(exc)) from exc
        finally:
            if restored is not None:
                try:
                    runtime.destroy(restored)
                except RuntimeCapabilityError as exc:
                    raise SessionControlError(f"runtime cleanup failed: {exc}") from exc
        try:
            runtime.cleanup_snapshot(snapshot)
        except RuntimeCapabilityError as exc:
            raise SessionControlError(f"snapshot cleanup failed: {exc}") from exc

        event = SessionEvent.create(
            session_id=session_id,
            sequence=recovery.session.current_sequence + 1,
            event_type=EventType.SESSION_RESUMED,
            actor=EventActor.SYSTEM,
            payload={
                "runtime_name": workspace.runtime_name,
                "snapshot_id": workspace.snapshot_id,
                "workspace_root": restored_workspace_root,
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
