from __future__ import annotations

from dataclasses import replace

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.committed_event_publisher import CommittedEventPublisherPort
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.workspace_projection_store import (
    WorkerProjectionCommitResult,
    WorkerProjectionTransactionPort,
)

from agent_storage.composition import ControlPlaneStores
from agent_storage.postgres_composition import PostgresControlPlaneStores


class PostCommitPublishingEventStore(EventStorePort):
    """Decorate direct Event appends with best-effort post-commit publication."""

    def __init__(
        self,
        event_store: EventStorePort,
        publisher: CommittedEventPublisherPort,
    ) -> None:
        self._event_store = event_store
        self._publisher = publisher

    def append(self, event: SessionEvent) -> SessionEvent:
        persisted = self._event_store.append(event)
        try:
            self._publisher.publish_committed(persisted)
        except Exception:
            # ponytail: live delivery is a hint; durable replay remains authoritative.
            pass
        return persisted

    def list_for_session(self, session_id: SessionId) -> list[SessionEvent]:
        return self._event_store.list_for_session(session_id)

    def read_since(self, session_id: SessionId, sequence: int) -> list[SessionEvent]:
        return self._event_store.read_since(session_id, sequence)


class PostCommitPublishingWorkerProjectionTransaction(WorkerProjectionTransactionPort):
    """Publish fenced aggregate Events only after their transaction commits."""

    def __init__(
        self,
        transaction: WorkerProjectionTransactionPort,
        publisher: CommittedEventPublisherPort,
    ) -> None:
        self._transaction = transaction
        self._publisher = publisher

    def commit_worker_event(
        self,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
        *,
        authority: WorkerMutationAuthority,
    ) -> WorkerProjectionCommitResult:
        committed = self._transaction.commit_worker_event(
            event,
            session,
            workspace,
            authority=authority,
        )
        self._publish(committed.event)
        return committed

    def project_persisted_worker_event(
        self,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
        *,
        authority: WorkerMutationAuthority,
    ) -> WorkerProjectionCommitResult:
        committed = self._transaction.project_persisted_worker_event(
            event,
            session,
            workspace,
            authority=authority,
        )
        self._publish(committed.event)
        return committed

    def _publish(self, event: SessionEvent) -> None:
        try:
            self._publisher.publish_committed(event)
        except Exception:
            # ponytail: Redis is a live hint; PostgreSQL replay is authoritative.
            pass


def with_committed_event_publisher[StoreBundle: ControlPlaneStores | PostgresControlPlaneStores](
    stores: StoreBundle,
    publisher: CommittedEventPublisherPort,
) -> StoreBundle:
    if isinstance(stores.events, PostCommitPublishingEventStore):
        return stores
    return replace(
        stores,
        events=PostCommitPublishingEventStore(stores.events, publisher),
    )


def with_worker_projection_publisher(
    transaction: WorkerProjectionTransactionPort,
    publisher: CommittedEventPublisherPort,
) -> WorkerProjectionTransactionPort:
    if isinstance(transaction, PostCommitPublishingWorkerProjectionTransaction):
        return transaction
    return PostCommitPublishingWorkerProjectionTransaction(transaction, publisher)
