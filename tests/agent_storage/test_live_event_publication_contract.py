from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    sqlite_control_plane_stores,
    with_committed_event_publisher,
    with_worker_projection_publisher,
)
from agent_storage.live_event_store import (
    PostCommitPublishingEventStore,
    PostCommitPublishingWorkerProjectionTransaction,
)


class _EventStore:
    def __init__(self, persisted: SessionEvent | None = None) -> None:
        self.persisted = persisted
        self.appended: list[SessionEvent] = []
        self.fail = False

    def append(self, event: SessionEvent) -> SessionEvent:
        if self.fail:
            raise ValueError("durable append failed")
        self.appended.append(event)
        return self.persisted or event

    def list_for_session(self, session_id: SessionId) -> list[SessionEvent]:
        return []

    def read_since(self, session_id: SessionId, sequence: int) -> list[SessionEvent]:
        return []


class _Publisher:
    def __init__(self) -> None:
        self.events: list[SessionEvent] = []
        self.fail = False

    def publish_committed(self, event: SessionEvent) -> None:
        if self.fail:
            raise ConnectionError("live publisher unavailable")
        self.events.append(event)


class _ProjectionTransaction:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[SessionEvent] = []

    def commit_worker_event(self, event: SessionEvent, *_args: Any, **_kwargs: Any) -> Any:
        self.calls.append(event)
        return self.result

    def project_persisted_worker_event(
        self, event: SessionEvent, *_args: Any, **_kwargs: Any
    ) -> Any:
        self.calls.append(event)
        return self.result


def _event(session_id: SessionId, sequence: int = 0) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "publish contract"},
    )


def test_successful_append_publishes_canonical_return_value() -> None:
    session_id = SessionId(uuid4())
    requested = _event(session_id)
    canonical = requested.model_copy(update={"sequence": 4})
    store = _EventStore(persisted=canonical)
    publisher = _Publisher()

    persisted = PostCommitPublishingEventStore(store, publisher).append(requested)

    assert persisted == canonical
    assert publisher.events == [canonical]


def test_append_failure_never_publishes() -> None:
    store = _EventStore()
    store.fail = True
    publisher = _Publisher()

    with pytest.raises(ValueError, match="durable append failed"):
        PostCommitPublishingEventStore(store, publisher).append(_event(SessionId(uuid4())))

    assert publisher.events == []


def test_publish_failure_does_not_hide_committed_event() -> None:
    event = _event(SessionId(uuid4()))
    store = _EventStore(persisted=event)
    publisher = _Publisher()
    publisher.fail = True

    assert PostCommitPublishingEventStore(store, publisher).append(event) == event
    assert store.appended == [event]


def test_duplicate_retry_is_safe_to_publish_again() -> None:
    event = _event(SessionId(uuid4()))
    store = _EventStore(persisted=event)
    publisher = _Publisher()
    decorated = PostCommitPublishingEventStore(store, publisher)

    decorated.append(event)
    decorated.append(event)

    assert publisher.events == [event, event]


def test_composition_wraps_event_store_once(tmp_path) -> None:
    stores = sqlite_control_plane_stores(tmp_path / "sessions.sqlite")
    publisher = _Publisher()

    wired = with_committed_event_publisher(stores, publisher)
    rewired = with_committed_event_publisher(wired, publisher)

    assert isinstance(wired.events, PostCommitPublishingEventStore)
    assert rewired.events is wired.events


def test_worker_aggregate_publishes_only_after_commit() -> None:
    event = _event(SessionId(uuid4()))
    result = type("CommitResult", (), {"event": event})()
    transaction = _ProjectionTransaction(result)
    publisher = _Publisher()
    decorated = with_worker_projection_publisher(transaction, publisher)

    committed = decorated.commit_worker_event(
        event,
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        authority=object(),  # type: ignore[arg-type]
    )

    assert committed is result
    assert transaction.calls == [event]
    assert publisher.events == [event]
    assert isinstance(decorated, PostCommitPublishingWorkerProjectionTransaction)


def test_worker_aggregate_failure_never_publishes() -> None:
    event = _event(SessionId(uuid4()))
    publisher = _Publisher()

    class _FailingTransaction(_ProjectionTransaction):
        def commit_worker_event(self, event: SessionEvent, *_args: Any, **_kwargs: Any) -> Any:
            raise ValueError("aggregate commit failed")

    decorated = with_worker_projection_publisher(_FailingTransaction(None), publisher)
    with pytest.raises(ValueError, match="aggregate commit failed"):
        decorated.commit_worker_event(
            event,
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            authority=object(),  # type: ignore[arg-type]
        )

    assert publisher.events == []
