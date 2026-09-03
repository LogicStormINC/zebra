from dataclasses import dataclass

from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import (
    rebuild_workspace,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_core.ports.workspace_projection_store import (
    WorkerProjectionTransactionPort,
    WorkspaceProjectionStorePort,
)

from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer


class SessionRecoveryError(ValueError):
    """Raised when a worker cannot recover a durable session."""


@dataclass(frozen=True)
class RecoveredSession:
    session: Session
    workspace: WorkspaceProjection
    event_count: int
    last_sequence: int
    is_terminal: bool


class SessionRecoveryService:
    def __init__(
        self,
        event_store: EventStorePort,
        projection_store: ProjectionStorePort,
        workspace_store: WorkspaceProjectionStorePort | None = None,
        *,
        worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
        deployment_namespace: str | None = None,
        model_call_indexer: ModelCallIndexer | None = None,
        tool_run_indexer: ToolRunIndexer | None = None,
    ) -> None:
        cloud_components = (
            worker_projection_transaction,
            deployment_namespace,
            model_call_indexer,
            tool_run_indexer,
        )
        if any(component is None for component in cloud_components) and any(
            component is not None for component in cloud_components
        ):
            raise ValueError(
                "cloud recovery requires projection transaction, namespace, and indexes"
            )
        self._event_store = event_store
        self._projection_store = projection_store
        self._workspace_store = workspace_store
        self._worker_projection_transaction = worker_projection_transaction
        self._deployment_namespace = deployment_namespace
        self._model_call_indexer = model_call_indexer
        self._tool_run_indexer = tool_run_indexer

    def recover_session(
        self,
        session_id: SessionId,
        *,
        worker_lease: WorkerLease | None = None,
    ) -> RecoveredSession:
        if self._worker_projection_transaction is not None:
            return self._recover_cloud_session(session_id, worker_lease=worker_lease)
        projected_session = self._projection_store.get_session(session_id)
        if projected_session is not None:
            delta_events = self._event_store.read_since(
                session_id,
                projected_session.current_sequence,
            )
            session = projected_session
            workspace = self._recover_workspace_projection(session_id)
            for event in delta_events:
                session = apply_event(session, event)
                workspace = apply_workspace_event(workspace, event)
            self._projection_store.save_session(session)
            if self._workspace_store is not None:
                self._workspace_store.save_workspace(workspace)
            return RecoveredSession(
                session=session,
                workspace=workspace,
                event_count=session.current_sequence + 1,
                last_sequence=session.current_sequence,
                is_terminal=session.status.value in {"completed", "failed", "cancelled"},
            )

        events = self._event_store.list_for_session(session_id)
        if not events:
            raise SessionRecoveryError("cannot recover missing session")

        session = rebuild_session(events)
        workspace = rebuild_workspace(events)
        self._projection_store.save_session(session)
        if self._workspace_store is not None:
            self._workspace_store.save_workspace(workspace)
        return RecoveredSession(
            session=session,
            workspace=workspace,
            event_count=len(events),
            last_sequence=events[-1].sequence,
            is_terminal=session.status.value in {"completed", "failed", "cancelled"},
        )

    def _recover_cloud_session(
        self,
        session_id: SessionId,
        *,
        worker_lease: WorkerLease | None,
    ) -> RecoveredSession:
        if worker_lease is None or worker_lease.session_id != session_id:
            raise SessionRecoveryError("cloud recovery requires the current Worker lease")
        projected_session = self._projection_store.get_session(session_id)
        projected_workspace = (
            None
            if self._workspace_store is None
            else self._workspace_store.get_workspace(session_id)
        )
        if projected_session is None or projected_workspace is None:
            raise SessionRecoveryError("cloud recovery requires primary projections")
        events = self._event_store.list_for_session(session_id)
        if not events:
            raise SessionRecoveryError("cannot recover missing session")
        projected_session, projected_workspace = self._align_cloud_primary_projections(
            projected_session,
            projected_workspace,
            events,
        )
        self._replay_cloud_indexes(events, worker_lease=worker_lease)

        session = projected_session
        workspace = projected_workspace
        transaction = self._worker_projection_transaction
        assert transaction is not None
        authority = self._authority(worker_lease, expected_stream_revision=session.current_sequence)
        for event in events:
            if event.sequence <= session.current_sequence:
                continue
            next_session = apply_event(session, event)
            next_workspace = apply_workspace_event(workspace, event)
            committed = transaction.project_persisted_worker_event(
                event,
                next_session,
                next_workspace,
                authority=authority,
            )
            session = committed.session
            workspace = committed.workspace
            authority = authority.model_copy(
                update={"expected_stream_revision": committed.event.sequence}
            )
        return RecoveredSession(
            session=session,
            workspace=workspace,
            event_count=len(events),
            last_sequence=session.current_sequence,
            is_terminal=session.status.value in {"completed", "failed", "cancelled"},
        )

    def _align_cloud_primary_projections(
        self,
        session: Session,
        workspace: WorkspaceProjection,
        events: list[SessionEvent],
    ) -> tuple[Session, WorkspaceProjection]:
        """Repair a one-sided control-plane projection write from canonical Events."""

        if workspace.current_sequence < session.current_sequence:
            for event in events:
                if workspace.current_sequence < event.sequence <= session.current_sequence:
                    workspace = apply_workspace_event(workspace, event)
            assert self._workspace_store is not None
            workspace = self._workspace_store.save_workspace(workspace)
        elif session.current_sequence < workspace.current_sequence:
            for event in events:
                if session.current_sequence < event.sequence <= workspace.current_sequence:
                    session = apply_event(session, event)
            session = self._projection_store.save_session(session)
        if workspace.current_sequence != session.current_sequence:
            raise SessionRecoveryError("cloud primary projections could not be aligned")
        return session, workspace

    def _replay_cloud_indexes(
        self,
        events: list[SessionEvent],
        *,
        worker_lease: WorkerLease,
    ) -> None:
        # ponytail: replay all Event-derived indexes at claim time so a crash between
        # a primary projection and its index cannot leave a durable hole; add an index
        # checkpoint if exceptionally long sessions make this O(n) recovery material.
        authority = self._authority(worker_lease, expected_stream_revision=-1)
        for event in events:
            assert self._model_call_indexer is not None
            assert self._tool_run_indexer is not None
            self._model_call_indexer.index_worker_event(event, authority=authority)
            self._tool_run_indexer.index_worker_event(event, authority=authority)
            authority = authority.model_copy(update={"expected_stream_revision": event.sequence})

    def _authority(
        self,
        worker_lease: WorkerLease,
        *,
        expected_stream_revision: int,
    ) -> WorkerMutationAuthority:
        assert self._deployment_namespace is not None
        return WorkerMutationAuthority(
            deployment_namespace=self._deployment_namespace,
            session_id=worker_lease.session_id,
            lease_fence=worker_lease.fence,
            expected_stream_revision=expected_stream_revision,
        )

    def _recover_workspace_projection(self, session_id: SessionId) -> WorkspaceProjection:
        if self._workspace_store is not None:
            projected_workspace = self._workspace_store.get_workspace(session_id)
            if projected_workspace is not None:
                delta_events = self._event_store.read_since(
                    session_id,
                    projected_workspace.current_sequence,
                )
                workspace = projected_workspace
                for event in delta_events:
                    workspace = apply_workspace_event(workspace, event)
                return workspace

        events = self._event_store.list_for_session(session_id)
        if not events:
            raise SessionRecoveryError("cannot recover missing session")
        return rebuild_workspace(events)
