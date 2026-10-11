"""Bounded durable AG-UI observation; execution/materialization stay outside SSE."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol
from uuid import UUID

from ag_ui.core import Event
from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventType
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports import LiveEventFanoutPort
from agent_core.ports.agent_tasks import TaskEvent
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_integrations.ag_ui import AgUiCursor, AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import ControlPlaneStores

from zebra_agent_api.ag_ui_checkpoint_tail import tail_checkpoint_frames
from zebra_agent_api.ag_ui_task_view import deadline_frames
from zebra_agent_api.ag_ui_task_view import stream_problem as _problem
from zebra_agent_api.responses import ApiResponse

_POLL_SECONDS = float(os.environ.get("ZEBRA_AGUI_POLL_SECONDS", "0.25"))
_KEEPALIVE_SECONDS = float(os.environ.get("ZEBRA_AGUI_KEEPALIVE_SECONDS", "3"))
_MAX_STREAM_SECONDS = float(os.environ.get("ZEBRA_AGUI_MAX_STREAM_SECONDS", "1800"))
_MAX_IDENTITY_TEXT = 256
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
    """Indexed, body-free preflight; never adopt/repair/materialize from GET."""
    path_identity = _stream_path_identity(path)
    if path_identity is None:
        return None
    thread_text, run_id = path_identity
    if not run_id or len(run_id) > _MAX_IDENTITY_TEXT:
        return _problem(400, "invalid_request", "runId is outside its bounds", path)
    try:
        task_id = TaskId(UUID(thread_text))
    except ValueError:
        return _problem(400, "invalid_request", "threadId must be a UUID", path)
    task = stores.tasks.get_task(task_id)
    if task is None:
        if stores.sessions.get_session(SessionId(UUID(thread_text))) is not None:
            response = _problem(
                409,
                "projection_not_ready",
                "Output index is not ready; retry observation later.",
                path,
            )
            response.body["retryable"] = True
            return response
        return _problem(404, "not_found", "AG-UI thread was not found", path)
    if stores.sessions.get_session(task.active_segment_id) is None:
        return _problem(409, "projection_incomplete", "active Segment is unavailable", path)
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id,
        thread_id=str(task_id),
        run_id=run_id,
    )
    cursor, error = _query_cursor(query, path)
    if error is not None:
        return error
    observer = AgUiCheckpointObserver(stores.tasks, namespace=deployment_namespace or "local")
    snapshot = None
    try:
        snapshot = observer.snapshot(task_id, identity)
        if command_outcome is not None and cursor is not None and snapshot.run.anchor is None:
            raise AgUiProjectionError("cursor has no canonical command anchor")
        observer.validate_cursor(snapshot, identity, cursor)
    except CheckpointNotReady:
        response = _problem(
            409,
            "projection_not_ready",
            "Output index is not ready; retry observation later.",
            path,
        )
        response.body["retryable"] = True
        return response
    except CheckpointConflict:
        return _problem(
            409, "projection_conflict", "Output index conflicts with canonical Events.", path
        )
    except AgUiProjectionError:
        response = _problem(400, "invalid_cursor", "cursor is not valid for this Task/run", path)
        recovery = observer.recovery_cursor(snapshot, identity) if snapshot is not None else None
        if recovery is not None:
            response.body["recovery_cursor"] = recovery.encode()
        return response
    except ValueError:
        return _problem(
            409,
            "projection_conflict",
            "Run metadata conflicts with canonical Events.",
            path,
        )
    return AgUiStreamContext(
        stores,
        task_id,
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
    authorization_seconds = (
        max(0.0, (context.authorization_expires_at - datetime.now(UTC)).total_seconds())
        if context.authorization_expires_at is not None
        else _MAX_STREAM_SECONDS
    )
    deadline = monotonic() + min(_MAX_STREAM_SECONDS, authorization_seconds)
    source = tail_checkpoint_frames(
        context,
        request,
        deadline,
        poll_seconds=_POLL_SECONDS,
        keepalive_seconds=_KEEPALIVE_SECONDS,
    )
    async for frame in deadline_frames(
        source, deadline, authorization_expires_at=context.authorization_expires_at
    ):
        yield frame


# Test/legacy oracle only. The actual SSE path above never hydrates Task history.
def _has_run_terminal_event(events: list[TaskEvent] | tuple[TaskEvent, ...], run_id: str) -> bool:
    binding = bind_task_run(events, run_id)
    return any(binding.includes(e) and e.event.event_type in _TERMINAL_EVENTS for e in events)


def _cursor_before_run(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    identity: AgUiRunIdentity,
) -> AgUiCursor | None:
    binding = bind_task_run(events, identity.run_id)
    previous = next((e for e in reversed(events) if e.task_sequence < binding.start), None)
    return (
        None
        if binding.anchor is None or previous is None
        else AgUiCursor(
            thread_id=identity.thread_id,
            run_id=identity.run_id,
            sequence=previous.task_sequence,
            event_id=str(previous.event.event_id),
        )
    )


def _run_command_is_not_indexed(
    events: list[TaskEvent] | tuple[TaskEvent, ...], run_id: str
) -> bool:
    binding = bind_task_run(events, run_id)
    return not binding.legacy and binding.anchor is None


def _project_new_task_events(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    identity: AgUiRunIdentity,
    after: AgUiCursor | None,
) -> Iterator[tuple[AgUiCursor, str]]:
    encoder = EventEncoder()
    for cursor, event in AgUiTaskProjector().project_task_events(events, identity, after=after):
        yield cursor, _encode_event(encoder, event, cursor)


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
    query: Mapping[str, str], path: str
) -> tuple[AgUiCursor | None, ApiResponse | None]:
    raw = query.get("cursor") or query.get("after") or query.get("last_event_id")
    if raw is None:
        return None, None
    try:
        return AgUiCursor.decode(raw), None
    except AgUiProjectionError:
        return None, _problem(400, "invalid_cursor", "cursor is malformed", path)
