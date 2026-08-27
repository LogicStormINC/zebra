"""Durable AG-UI replay and live-tail composition."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Protocol
from uuid import UUID

from ag_ui.core import Event
from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui import (
    AgUiCursor,
    AgUiProjectionError,
    AgUiRunIdentity,
)
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse

_POLL_SECONDS = float(os.environ.get("ZEBRA_AGUI_POLL_SECONDS", "0.25"))
_KEEPALIVE_SECONDS = float(os.environ.get("ZEBRA_AGUI_KEEPALIVE_SECONDS", "3"))
_TERMINAL_FLUSH_SECONDS = float(os.environ.get("ZEBRA_AGUI_TERMINAL_FLUSH_SECONDS", "0.5"))
_MAX_STREAM_SECONDS = float(os.environ.get("ZEBRA_AGUI_MAX_STREAM_SECONDS", "1800"))
_MAX_IDENTITY_TEXT = 256
logger = logging.getLogger(__name__)
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
    task_id: TaskId
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
    if stores.sessions.get_session(task.active_segment_id) is None:
        return _problem(409, "projection_incomplete", "active Segment is unavailable", path)
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id,
        thread_id=thread_text,
        run_id=run_id,
    )
    cursor, error = _query_cursor(query, path)
    if error is not None:
        return error
    try:
        AgUiTaskProjector().project_task(
            stores.tasks.read_events(thread_id, -1),
            identity,
            after=cursor,
        )
    except AgUiProjectionError:
        return _problem(400, "invalid_cursor", "cursor is not valid for this Task/run", path)
    return AgUiStreamContext(stores, thread_id, identity, cursor)


async def tail_agui_events(
    context: AgUiStreamContext,
    request: _DisconnectableRequest,
) -> AsyncIterator[str]:
    """Replay durable Events, then poll the same authority for a lossless tail.

    The loop never trusts a single signal for liveness: client disconnects
    surface as errors on ``yield``; store hiccups are retried; and the whole
    tail is bounded by a wall-clock deadline.
    """

    cursor = context.cursor
    last_delivery = monotonic()
    deadline = monotonic() + _MAX_STREAM_SECONDS
    iterations = 0
    failures = 0
    del request  # disconnects are detected at yield time
    while monotonic() < deadline:
        iterations += 1
        try:
            events = await asyncio.to_thread(
                context.stores.tasks.read_events,
                context.task_id,
                -1,
            )
        except Exception:
            failures += 1
            if failures > 20:
                return
            await asyncio.sleep(_POLL_SECONDS)
            continue
        emitted = False
        try:
            for next_cursor, projected in _project_new_task_events(
                events,
                context.identity,
                cursor,
            ):
                cursor = next_cursor
                emitted = True
                last_delivery = monotonic()
                yield projected
        except Exception:
            failures += 1
            if failures > 20:
                return
            await asyncio.sleep(_POLL_SECONDS)
            continue
        try:
            task = await asyncio.to_thread(
                context.stores.tasks.get_task,
                context.task_id,
            )
        except Exception:
            failures += 1
            if failures > 20:
                return
            await asyncio.sleep(_POLL_SECONDS)
            continue
        if task is None:
            return
        if events and events[-1].event.event_type in _TERMINAL_EVENTS:
            return
        if task.status in _TERMINAL_STATUSES:
            return
        if not emitted and monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
            last_delivery = monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(_POLL_SECONDS)


def _project_new_task_events(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    identity: AgUiRunIdentity,
    after: AgUiCursor | None,
) -> list[tuple[AgUiCursor, str]]:
    """Project one Task event at a time so every SSE id is an exact cursor.

    ponytail: replaying the bounded Task stream for each new event is
    intentionally simple and keeps cursor-to-event attribution exact across
    Segment rollovers; a larger deployment can replace this with a stateful
    projector without changing the wire contract.
    """

    start_sequence = after.sequence if after is not None else -1
    previous = after
    encoder = EventEncoder()
    projector = AgUiTaskProjector()
    projected: list[tuple[AgUiCursor, str]] = []
    for index, entry in enumerate(events):
        if entry.task_sequence <= start_sequence:
            continue
        projection = projector.project_task(
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
