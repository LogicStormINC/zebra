"""Durable AG-UI replay and live-tail composition."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol
from uuid import UUID

from ag_ui.core import Event, RunErrorEvent
from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import LiveEventCursor, LiveEventFanoutPort
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui import (
    AgUiCursor,
    AgUiProjectionError,
    AgUiRunIdentity,
)
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import ControlPlaneStores

from zebra_agent_api.ag_ui_task_view import canonical_task_view, deadline_frames
from zebra_agent_api.ag_ui_task_view import stream_problem as _problem
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
    command_outcome: Callable[[TaskId, str, UUID, HostContextEnvelope], str | None] | None = None
    host_context: HostContextEnvelope | None = None


def prepare_agui_stream(
    stores: ControlPlaneStores,
    path: str,
    query: Mapping[str, str],
    *,
    live_event_fanout: LiveEventFanoutPort | None = None,
    deployment_namespace: str | None = None,
    authorization_expires_at: datetime | None = None,
    command_outcome: Callable[[TaskId, str, UUID, HostContextEnvelope], str | None] | None = None,
    host_context: HostContextEnvelope | None = None,
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
        view = canonical_task_view(stores, thread_id)
        if (
            command_outcome is not None
            and cursor is not None
            and bind_task_run(view, run_id).anchor is None
        ):
            raise AgUiProjectionError("cursor has no canonical run anchor")
        AgUiTaskProjector().project_task(
            view,
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
        command_outcome,
        host_context,
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

    authorization_seconds = (
        max(0.0, (context.authorization_expires_at - datetime.now(UTC)).total_seconds())
        if context.authorization_expires_at is not None
        else _MAX_STREAM_SECONDS
    )
    deadline = monotonic() + min(_MAX_STREAM_SECONDS, authorization_seconds)
    async for frame in deadline_frames(_tail_agui_events(context, request, deadline), deadline):
        yield frame


async def _tail_agui_events(
    context: AgUiStreamContext,
    request: _DisconnectableRequest,
    deadline: float,
) -> AsyncGenerator[str, None]:
    cursor = context.cursor
    last_delivery = monotonic()
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
                        canonical_task_view,
                        context.stores,
                        context.task_id,
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
        try:
            bind_task_run(events, context.identity.run_id)
        except AgUiProjectionError:
            yield EventEncoder().encode(
                RunErrorEvent(
                    code="invalid_run_binding", message="The run has an ambiguous command binding."
                )
            )
            return
        if cursor is None:
            if (
                context.command_outcome is not None
                and bind_task_run(events, context.identity.run_id).anchor is None
            ):
                await asyncio.sleep(_POLL_SECONDS)
                continue
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
        binding = bind_task_run(events, context.identity.run_id)
        if (
            context.command_outcome is not None
            and context.host_context is not None
            and binding.anchor is not None
        ):
            try:
                outcome = await asyncio.to_thread(
                    context.command_outcome,
                    context.task_id,
                    context.identity.run_id,
                    binding.anchor.event.event_id,
                    context.host_context,
                )
            except Exception:
                failures += 1
                if failures > 20:
                    return
                await asyncio.sleep(_POLL_SECONDS)
                continue
            if outcome in {
                "command_requires_reconciliation",
                "command_unsupported",
                "command_recovery_exhausted",
                "command_delivery_failed",
            }:
                yield EventEncoder().encode(
                    RunErrorEvent(
                        code=outcome,
                        message="The command could not proceed. Refresh or contact an operator.",
                    )
                )
                return
        if task.active_segment_id != context.identity.session_id:
            context = replace(
                context,
                identity=context.identity.model_copy(update={"session_id": task.active_segment_id}),
            )
            task_index_ready = False
            live_cursor = None
        if (
            task.status in _TERMINAL_STATUSES
            and bind_task_run(events, context.identity.run_id).legacy
        ):
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
    binding = bind_task_run(events, run_id)
    return any(
        binding.includes(entry) and entry.event.event_type in _TERMINAL_EVENTS for entry in events
    )


def _cursor_before_run(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    identity: AgUiRunIdentity,
) -> AgUiCursor | None:
    binding = bind_task_run(events, identity.run_id)
    preceding = [e for e in events if e.task_sequence < binding.start]
    if binding.anchor is not None and preceding:
        previous = preceding[-1]
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
    binding = bind_task_run(events, run_id)
    return not binding.legacy and binding.anchor is None


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
    binding = bind_task_run(events, identity.run_id)
    for index, entry in enumerate(events):
        if entry.task_sequence <= start_sequence or not binding.includes(entry):
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
