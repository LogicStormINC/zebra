"""Durable AG-UI replay and live-tail composition."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol
from uuid import UUID

from ag_ui.core import Event
from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import LiveEventCursor, LiveEventFanoutPort
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
_TERMINAL_FLUSH_SECONDS = float(os.environ.get("ZEBRA_AGUI_TERMINAL_FLUSH_SECONDS", "2"))
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
        EventType.TURN_COMPLETED,
        EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED,
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
    live_event_fanout: LiveEventFanoutPort | None = None
    deployment_namespace: str | None = None
    authorization_expires_at: datetime | None = None


def prepare_agui_stream(
    stores: ControlPlaneStores,
    path: str,
    query: Mapping[str, str],
    *,
    live_event_fanout: LiveEventFanoutPort | None = None,
    deployment_namespace: str | None = None,
    authorization_expires_at: datetime | None = None,
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
    return AgUiStreamContext(
        stores,
        thread_id,
        identity,
        cursor,
        live_event_fanout,
        deployment_namespace,
        authorization_expires_at,
    )


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
    authorization_seconds = (
        max(0.0, (context.authorization_expires_at - datetime.now(UTC)).total_seconds())
        if context.authorization_expires_at is not None
        else _MAX_STREAM_SECONDS
    )
    deadline = monotonic() + min(_MAX_STREAM_SECONDS, authorization_seconds)
    iterations = 0
    failures = 0
    terminal_status_since: float | None = None
    events: list[TaskEvent] = []
    task_index_ready = False
    live_cursor: LiveEventCursor | None = None
    if context.live_event_fanout is not None and context.deployment_namespace is not None:
        try:
            live_cursor = await asyncio.to_thread(
                context.live_event_fanout.capture_barrier,
                deployment_namespace=context.deployment_namespace,
                session_id=context.identity.session_id,
            )
        except Exception:
            # ponytail: PostgreSQL polling remains the lossless fallback.
            live_cursor = None
    del request  # disconnects are detected at yield time
    while monotonic() < deadline:
        iterations += 1
        waited_for_live = False
        try:
            if task_index_ready:
                events = await asyncio.to_thread(
                    _extend_with_live_segment_events,
                    context,
                    events,
                )
            else:
                events = list(
                    await asyncio.to_thread(
                        context.stores.tasks.read_events,
                        context.task_id,
                        -1,
                    )
                )
            if (
                task_index_ready
                and live_cursor is not None
                and context.live_event_fanout is not None
                and context.deployment_namespace is not None
            ):
                live_batch = await asyncio.to_thread(
                    context.live_event_fanout.read_after,
                    deployment_namespace=context.deployment_namespace,
                    session_id=context.identity.session_id,
                    barrier=live_cursor,
                    durable_sequence=_latest_segment_sequence(context, events),
                    count=100,
                    block_ms=max(1, int(_POLL_SECONDS * 1_000)),
                )
                waited_for_live = True
                live_cursor = live_batch.next_cursor
                events = _extend_with_session_events(
                    context,
                    events,
                    [envelope.event for envelope in live_batch.events],
                )
        except Exception:
            failures += 1
            live_cursor = None
            if failures > 20:
                return
            await asyncio.sleep(_POLL_SECONDS)
            continue
        if cursor is None:
            cursor = _cursor_before_run(events, context.identity)
            if cursor is None and _run_command_is_not_indexed(events, context.identity.run_id):
                await asyncio.sleep(_POLL_SECONDS)
                continue
        task_index_ready = True
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
        if _has_run_terminal_event(events, context.identity.run_id):
            return
        if task.status in _TERMINAL_STATUSES:
            now = monotonic()
            terminal_status_since = terminal_status_since or now
            if now - terminal_status_since >= _TERMINAL_FLUSH_SECONDS:
                return
        else:
            terminal_status_since = None
        if not emitted and monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
            last_delivery = monotonic()
            yield ": keepalive\n\n"
        if not waited_for_live:
            await asyncio.sleep(_POLL_SECONDS)


def _extend_with_live_segment_events(
    context: AgUiStreamContext,
    task_events: list[TaskEvent],
) -> list[TaskEvent]:
    """Overlay the active Segment's durable tail while its Task index is stale."""

    return _extend_with_session_events(
        context,
        task_events,
        context.stores.events.read_since(
            context.identity.session_id,
            _latest_segment_sequence(context, task_events),
        ),
    )


def _extend_with_session_events(
    context: AgUiStreamContext,
    task_events: list[TaskEvent],
    session_events: Sequence[SessionEvent],
) -> list[TaskEvent]:
    events = list(task_events)
    known_event_ids = {str(entry.event.event_id) for entry in events}
    task_sequence = max((entry.task_sequence for entry in events), default=-1)
    for event in session_events:
        event_id = str(event.event_id)
        if event_id in known_event_ids:
            continue
        task_sequence += 1
        events.append(
            TaskEvent(
                task_id=context.task_id,
                task_sequence=task_sequence,
                segment_id=context.identity.session_id,
                segment_sequence=event.sequence,
                event=event,
            )
        )
        known_event_ids.add(event_id)
    return events


def _latest_segment_sequence(
    context: AgUiStreamContext,
    task_events: list[TaskEvent],
) -> int:
    return max(
        (
            entry.segment_sequence
            for entry in task_events
            if entry.segment_id == context.identity.session_id
        ),
        default=-1,
    )


def _has_run_terminal_event(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    run_id: str,
) -> bool:
    run_start: int | None = None
    command_seen = False
    for entry in events:
        if entry.event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
            continue
        command_seen = True
        if _command_run_id(entry) == run_id:
            run_start = entry.task_sequence
    if run_start is None:
        # A stream opened before its command must not close on another run's
        # terminal event. Command-less fixtures retain legacy replay behavior.
        if command_seen:
            return False
        run_start = -1
    return any(
        entry.task_sequence > run_start and entry.event.event_type in _TERMINAL_EVENTS
        for entry in events
    )


def _cursor_before_run(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    identity: AgUiRunIdentity,
) -> AgUiCursor | None:
    for index, entry in enumerate(events):
        if entry.event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
            continue
        if _command_run_id(entry) != identity.run_id or index == 0:
            continue
        previous = events[index - 1]
        return AgUiCursor(
            thread_id=identity.thread_id,
            run_id=identity.run_id,
            sequence=previous.task_sequence,
            event_id=str(previous.event.event_id),
        )
    return None


def _run_command_is_not_indexed(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    run_id: str,
) -> bool:
    command_run_ids = {
        candidate
        for entry in events
        if entry.event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        if (candidate := _command_run_id(entry)) is not None
    }
    return bool(command_run_ids) and run_id not in command_run_ids


def _command_run_id(entry: TaskEvent) -> str | None:
    payload = entry.event.payload
    command_payload = payload.get("payload")
    candidate = payload.get("run_id")
    if isinstance(command_payload, Mapping):
        candidate = command_payload.get("run_id", candidate)
    return candidate if isinstance(candidate, str) else None


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
