from __future__ import annotations

from dataclasses import replace

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.committed_event_publisher import CommittedEventPublisherPort
from agent_core.ports.event_store import EventStorePort

from agent_storage.composition import ControlPlaneStores


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


def with_committed_event_publisher(
    stores: ControlPlaneStores,
    publisher: CommittedEventPublisherPort,
) -> ControlPlaneStores:
    if isinstance(stores.events, PostCommitPublishingEventStore):
        return stores
    return replace(
        stores,
        events=PostCommitPublishingEventStore(stores.events, publisher),
    )
