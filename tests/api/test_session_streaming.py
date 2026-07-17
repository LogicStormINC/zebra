import asyncio
from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.session_streaming import tail_session_events


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_session_stream_replays_then_tails_until_terminal_state(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Streaming session",
            user_input="Stream the response.",
            workspace_root=tmp_path.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    model_call_id = "00000000-0000-0000-0000-000000000146"

    async def collect() -> list[str]:
        async def produce() -> None:
            await asyncio.sleep(0.02)
            next_sequence = bootstrap.session.current_sequence + 1
            for event_type, payload in (
                (
                    EventType.MODEL_REQUEST_STARTED,
                    {"attempt_number": 1, "model_call_id": model_call_id},
                ),
                (
                    EventType.MODEL_RESPONSE_DELTA,
                    {
                        "attempt_number": 1,
                        "model_call_id": model_call_id,
                        "delta_index": 0,
                        "content_delta": "first chunk",
                    },
                ),
                (
                    EventType.SESSION_COMPLETED,
                    {"attempt_number": 1, "summary": "done", "metadata": {}},
                ),
            ):
                event_store.append(
                    SessionEvent.create(
                        session_id=bootstrap.session.session_id,
                        sequence=next_sequence,
                        event_type=event_type,
                        actor=EventActor.HARNESS,
                        payload=payload,
                        created_at=datetime.now(UTC),
                    )
                )
                next_sequence += 1
            SQLiteProjectionStore(database_path).save_session(
                rebuild_session(
                    event_store.list_for_session(bootstrap.session.session_id)
                )
            )

        producer = asyncio.create_task(produce())
        chunks = [
            chunk
            async for chunk in tail_session_events(
                database_path=database_path,
                session_id=bootstrap.session.session_id,
                request=_ConnectedRequest(),  # type: ignore[arg-type]
                after_sequence=bootstrap.session.current_sequence,
            )
        ]
        await producer
        return chunks

    chunks = asyncio.run(collect())

    assert len(chunks) == 3
    assert '"event_type": "model_response_delta"' in chunks[1]
    assert '"content_delta": "first chunk"' in chunks[1]
    assert '"event_type": "session_completed"' in chunks[2]
