from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from time import monotonic

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import LiveEventCursor, LiveEventFanoutPort
from agent_storage import ControlPlaneStores, sqlite_control_plane_stores
from fastapi import Request

from zebra_agent_api.task_api import is_user_task_event, serialize_task_event

_POLL_SECONDS = 0.05
_KEEPALIVE_SECONDS = 15.0
# awaiting_turn keeps a conversation Task stream open between Turns (ADR-026).
_ACTIVE_STATUSES = frozenset(
    {SessionStatus.READY, SessionStatus.RUNNING, SessionStatus.AWAITING_TURN}
)


async def tail_session_events(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    live_event_fanout: LiveEventFanoutPort | None = None,
    deployment_namespace: str | None = None,
    session_id: SessionId,
    request: Request,
    after_sequence: int,
) -> AsyncIterator[str]:
    active_stores = stores or sqlite_control_plane_stores(database_path)
    cursor = after_sequence
    live_cursor: LiveEventCursor | None = None
    if live_event_fanout is not None and deployment_namespace is not None:
        try:
            live_cursor = await asyncio.to_thread(
                live_event_fanout.capture_barrier,
                deployment_namespace=deployment_namespace,
                session_id=session_id,
            )
        except Exception:
            # ponytail: durable polling is the lossless fallback when Redis is unavailable.
            live_cursor = None
    last_delivery = monotonic()
    while not await request.is_disconnected():
        events = await asyncio.to_thread(active_stores.events.read_since, session_id, cursor)
        for event in events:
            cursor = event.sequence
            last_delivery = monotonic()
            yield encode_sse_event(event)
        if events:
            continue
        if live_event_fanout is not None and deployment_namespace is not None and live_cursor:
            try:
                live_batch = await asyncio.to_thread(
                    live_event_fanout.read_after,
                    deployment_namespace=deployment_namespace,
                    session_id=session_id,
                    barrier=live_cursor,
                    durable_sequence=cursor,
                    count=100,
                    block_ms=1_000,
                )
                live_cursor = live_batch.next_cursor
                for envelope in live_batch.events:
                    if envelope.event.sequence <= cursor:
                        continue
                    cursor = envelope.event.sequence
                    last_delivery = monotonic()
                    yield encode_sse_event(envelope.event)
                if live_batch.events:
                    continue
            except Exception:
                # ponytail: once live delivery fails, durable polling converges the stream.
                live_cursor = None
        session = await asyncio.to_thread(active_stores.sessions.get_session, session_id)
        if session is None or session.status not in _ACTIVE_STATUSES:
            return
        if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
            last_delivery = monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(_POLL_SECONDS)


async def tail_task_events(
    *,
    database_path: Path,
    stores: ControlPlaneStores | None = None,
    task_id: TaskId,
    request: Request,
    after_sequence: int,
) -> AsyncIterator[str]:
    store = (stores or sqlite_control_plane_stores(database_path)).tasks
    cursor = after_sequence
    last_delivery = monotonic()
    while not await request.is_disconnected():
        events = await asyncio.to_thread(store.read_events, task_id, cursor)
        for event in events:
            cursor = event.task_sequence
            if not is_user_task_event(event):
                continue
            last_delivery = monotonic()
            payload = serialize_task_event(event)
            yield (
                f"id: {event.task_sequence}\n"
                "event: task_event\n"
                f"data: {json.dumps(payload, sort_keys=True)}\n\n"
            )
        if events:
            continue
        task = await asyncio.to_thread(store.get_task, task_id)
        if task is None or task.status not in _ACTIVE_STATUSES:
            return
        if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
            last_delivery = monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(_POLL_SECONDS)


def encode_sse_event(event: SessionEvent) -> str:
    payload = {
        "event_id": str(event.event_id),
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "actor": event.actor.value,
        "created_at": event.created_at.isoformat(),
        "payload": event.payload,
    }
    return (
        f"id: {event.sequence}\n"
        "event: session_event\n"
        f"data: {json.dumps(payload, sort_keys=True)}\n\n"
    )
