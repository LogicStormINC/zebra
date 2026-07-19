from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from time import monotonic

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from fastapi import Request

from zebra_agent_api.task_api import is_user_task_event, serialize_task_event

_POLL_SECONDS = 0.05
_KEEPALIVE_SECONDS = 15.0
_ACTIVE_STATUSES = frozenset({SessionStatus.READY, SessionStatus.RUNNING})


async def tail_session_events(
    *,
    database_path: Path,
    session_id: SessionId,
    request: Request,
    after_sequence: int,
) -> AsyncIterator[str]:
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    cursor = after_sequence
    last_delivery = monotonic()
    while not await request.is_disconnected():
        events = await asyncio.to_thread(event_store.read_since, session_id, cursor)
        for event in events:
            cursor = event.sequence
            last_delivery = monotonic()
            yield encode_sse_event(event)
        if events:
            continue
        session = await asyncio.to_thread(projection_store.get_session, session_id)
        if session is None or session.status not in _ACTIVE_STATUSES:
            return
        if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
            last_delivery = monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(_POLL_SECONDS)


async def tail_task_events(
    *,
    database_path: Path,
    task_id: TaskId,
    request: Request,
    after_sequence: int,
) -> AsyncIterator[str]:
    store = SQLiteAgentTaskStore(database_path)
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
