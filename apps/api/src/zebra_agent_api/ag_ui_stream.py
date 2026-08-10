"""Durable AG-UI replay and live-tail composition."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Protocol
from uuid import UUID

from ag_ui.core import Event
from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_integrations.ag_ui import (
    AgUiCursor,
    AgUiProjectionError,
    AgUiProjector,
    AgUiRunIdentity,
)
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse

_POLL_SECONDS = 0.05
_KEEPALIVE_SECONDS = 15.0
_MAX_IDENTITY_TEXT = 256
_STREAM_PATH_PREFIX = "/agui/threads/"
_TERMINAL_EVENTS = frozenset(
    {
        EventType.SESSION_COMPLETED,
        EventType.SESSION_FAILED,
        EventType.SESSION_CANCELLED,
        EventType.APPROVAL_REQUESTED,
        EventType.CLARIFICATION_REQUESTED,
    }
)
_TERMINAL_STATUSES = frozenset(
    {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED}
)


class _DisconnectableRequest(Protocol):
    async def is_disconnected(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class AgUiStreamContext:
    stores: ControlPlaneStores
    session_id: SessionId
    identity: AgUiRunIdentity
    cursor: AgUiCursor | None


def prepare_agui_stream(
    stores: ControlPlaneStores,
    path: str,
    query: Mapping[str, str],
) -> AgUiStreamContext | ApiResponse | None:
    """Resolve and validate a stream before HTTP sends response headers."""

    path_identity = _stream_path_identity(path)
    if path_identity is None:
        return None
    thread_text, run_id = path_identity
    if not run_id or len(run_id) > _MAX_IDENTITY_TEXT:
        return _problem(400, "invalid_request", "runId is outside its bounds", path)
    try:
        thread_id = TaskId(UUID(thread_text))
    except ValueError:
        return _problem(400, "invalid_request", "threadId must be a UUID", path)
    task = stores.tasks.get_task(thread_id)
    if task is None:
        return _problem(404, "not_found", "AG-UI thread was not found", path)
    session_id = task.active_segment_id
    if stores.sessions.get_session(session_id) is None:
        return _problem(409, "projection_incomplete", "active Segment is unavailable", path)
    identity = AgUiRunIdentity(
        session_id=session_id,
        thread_id=thread_text,
        run_id=run_id,
    )
    cursor, error = _query_cursor(query, path)
    if error is not None:
        return error
    try:
        AgUiProjector().project(stores.events.list_for_session(session_id), identity, after=cursor)
    except AgUiProjectionError:
        return _problem(400, "invalid_cursor", "cursor is not valid for this Task/run", path)
    return AgUiStreamContext(stores, session_id, identity, cursor)


async def tail_agui_events(
    context: AgUiStreamContext,
    request: _DisconnectableRequest,
) -> AsyncIterator[str]:
    """Replay durable Events, then poll the same authority for a lossless tail."""

    cursor = context.cursor
    last_delivery = monotonic()
    while not await request.is_disconnected():
        events = await asyncio.to_thread(
            context.stores.events.list_for_session,
            context.session_id,
        )
        emitted = False
        for next_cursor, projected in _project_new_events(
            events,
            context.identity,
            cursor,
        ):
            cursor = next_cursor
            emitted = True
            last_delivery = monotonic()
            yield projected
        session = await asyncio.to_thread(
            context.stores.sessions.get_session,
            context.session_id,
        )
        if session is None:
            return
        if events and events[-1].event_type in _TERMINAL_EVENTS:
            return
        if session.status in _TERMINAL_STATUSES:
            return
        if emitted:
            continue
        if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
            last_delivery = monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(_POLL_SECONDS)


def _project_new_events(
    events: list[SessionEvent],
    identity: AgUiRunIdentity,
    after: AgUiCursor | None,
) -> list[tuple[AgUiCursor, str]]:
    """Project one durable Event at a time so every SSE id is an exact cursor.

    ponytail: replaying the bounded stream for each new Event is intentionally
    simple and keeps cursor-to-event attribution exact; a larger deployment can
    replace this with a stateful projector without changing the wire contract.
    """

    start_sequence = after.sequence if after is not None else -1
    previous = after
    encoder = EventEncoder()
    projected: list[tuple[AgUiCursor, str]] = []
    for index, event in enumerate(events):
        if event.sequence <= start_sequence:
            continue
        projection = AgUiProjector().project(
            events[: index + 1],
            identity,
            after=previous,
        )
        next_cursor = projection.next_cursor
        if next_cursor is None:
            continue
        for agui_event in projection.events:
            projected.append((next_cursor, _encode_event(encoder, agui_event, next_cursor)))
        previous = next_cursor
    return projected


def _encode_event(encoder: EventEncoder, event: Event, cursor: AgUiCursor) -> str:
    return f"id: {cursor.encode()}\n{encoder.encode(event)}"


def _stream_path_identity(path: str) -> tuple[str, str] | None:
    parts = tuple(part for part in path.split("/") if part)
    if (
        len(parts) == 6
        and path.startswith(_STREAM_PATH_PREFIX)
        and parts[:2] == ("agui", "threads")
        and parts[3] == "runs"
        and parts[5] == "stream"
    ):
        return parts[2], parts[4]
    return None


def _query_cursor(
    query: Mapping[str, str],
    path: str,
) -> tuple[AgUiCursor | None, ApiResponse | None]:
    raw = query.get("cursor") or query.get("after") or query.get("last_event_id")
    if raw is None:
        return None, None
    try:
        return AgUiCursor.decode(raw), None
    except AgUiProjectionError:
        return None, _problem(400, "invalid_cursor", "cursor is malformed", path)


def _problem(status: int, code: str, detail: str, path: str) -> ApiResponse:
    return ApiResponse(
        status,
        {
            "type": f"https://zebra.invalid/problems/{code}",
            "title": "AG-UI stream rejected",
            "status": status,
            "detail": detail[:512],
            "instance": path,
            "code": code,
        },
    )
