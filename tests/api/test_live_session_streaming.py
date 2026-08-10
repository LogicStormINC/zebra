from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.live_event_fanout import (
    LiveEventBatch,
    LiveEventCursor,
    LiveEventEnvelope,
)
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.session_streaming import tail_session_events


class _DisconnectAfter:
    def __init__(self, connected_checks: int) -> None:
        self._connected_checks = connected_checks
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._connected_checks


class _LiveFanout:
    def __init__(self, event: SessionEvent | None = None, *, fail: bool = False) -> None:
        self.event = event
        self.fail = fail
        self.captured = False
        self.reads = 0

    def capture_barrier(
        self, *, deployment_namespace: str, session_id: SessionId
    ) -> LiveEventCursor:
        assert deployment_namespace == "live-test"
        if self.event is not None:
            assert session_id == self.event.session_id
        self.captured = True
        return LiveEventCursor("0-0", stream_ref="live-test")

    def publish(self, *, deployment_namespace: str, event: SessionEvent) -> LiveEventCursor:
        del deployment_namespace, event
        return LiveEventCursor("1-0")

    def read_after(
        self,
        *,
        deployment_namespace: str,
        session_id: SessionId,
        barrier: LiveEventCursor,
        durable_sequence: int,
        count: int = 100,
        block_ms: int = 0,
    ) -> LiveEventBatch:
        del deployment_namespace, session_id, durable_sequence, count, block_ms
        assert self.captured
        assert barrier.value == "0-0"
        self.reads += 1
        if self.fail:
            raise ConnectionError("redis unavailable")
        assert self.event is not None
        envelope = LiveEventEnvelope(
            deployment_namespace="live-test",
            event=self.event,
            cursor=LiveEventCursor("1-0", stream_ref="live-test"),
        )
        return LiveEventBatch(
            events=(envelope, envelope),
            next_cursor=envelope.cursor,
        )


def test_sse_replays_durable_then_filters_duplicate_live_entries(tmp_path: Path) -> None:
    database_path, session_id, revision = _seed_session(tmp_path)
    event = _live_event(session_id, revision + 1)
    fanout = _LiveFanout(event)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in tail_session_events(
                database_path=database_path,
                session_id=session_id,
                request=_DisconnectAfter(1),  # type: ignore[arg-type]
                after_sequence=revision,
                live_event_fanout=fanout,  # type: ignore[arg-type]
                deployment_namespace="live-test",
            )
        ]

    chunks = asyncio.run(collect())

    assert len(chunks) == 1
    assert '"event_type": "model_request_started"' in chunks[0]
    assert fanout.reads == 1


def test_sse_falls_back_to_durable_polling_when_live_read_fails(tmp_path: Path) -> None:
    database_path, session_id, revision = _seed_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    attempt = SessionEvent.create(
        session_id=session_id,
        sequence=revision + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=datetime.now(UTC),
    )
    event_store.append(attempt)
    projection_store.save_session(rebuild_session(event_store.list_for_session(session_id)))
    event = SessionEvent.create(
        session_id=session_id,
        sequence=revision + 2,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "summary": "done", "metadata": {}},
        created_at=datetime.now(UTC),
    )
    fanout = _LiveFanout(fail=True)

    async def produce() -> None:
        await asyncio.sleep(0.02)
        event_store.append(event)
        projection_store.save_session(rebuild_session(event_store.list_for_session(session_id)))

    async def collect() -> list[str]:
        producer = asyncio.create_task(produce())
        chunks = [
            chunk
            async for chunk in tail_session_events(
                database_path=database_path,
                session_id=session_id,
                request=_DisconnectAfter(100),  # type: ignore[arg-type]
                after_sequence=revision + 1,
                live_event_fanout=fanout,  # type: ignore[arg-type]
                deployment_namespace="live-test",
            )
        ]
        await producer
        return chunks

    chunks = asyncio.run(collect())

    assert len(chunks) == 1
    assert '"event_type": "session_completed"' in chunks[0]
    assert fanout.reads == 1


def _seed_session(tmp_path: Path) -> tuple[Path, SessionId, int]:
    database_path = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Live SSE",
            user_input="Stream live events.",
            workspace_root=tmp_path.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return database_path, bootstrap.session.session_id, bootstrap.session.current_sequence


def _live_event(session_id: SessionId, sequence: int) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.MODEL_REQUEST_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "model_call_id": str(uuid4())},
    )
