"""Read-only canonical Task coordinates for initial replay and rollover refresh."""

from asyncio import timeout, to_thread
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from math import isfinite
from time import monotonic

import psycopg
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import TaskEvent
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_integrations.ag_ui import AgUiProjectionError
from agent_storage import ControlPlaneStores
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline

from zebra_agent_api.responses import ApiResponse


async def authorized_task_preflight[T](
    authorize: Callable[[], ApiResponse | None],
    prepare: Callable[[], T],
    *,
    authorization_expires_at: datetime | None,
    request_deadline: float | None = None,
) -> T | ApiResponse:
    """Move all read-only preflight off the loop under one grant-bounded budget."""

    def operation() -> T | ApiResponse:
        _check_read_deadline(current_task_io_deadline(), authorization_expires_at)
        denied = authorize()
        _check_read_deadline(current_task_io_deadline(), authorization_expires_at)
        return denied if denied is not None else prepare()

    return await authorized_async_read(
        lambda: to_thread(operation),
        authorization_expires_at=authorization_expires_at,
        request_deadline=request_deadline,
    )


async def authorized_async_read[T](
    read: Callable[[], Awaitable[T]],
    *,
    authorization_expires_at: datetime | None,
    request_deadline: float | None = None,
) -> T | ApiResponse:
    """One scope also covers async adapters and their context-propagating thread reads."""
    seconds = min(
        2.0,
        max(0, (authorization_expires_at - datetime.now(UTC)).total_seconds())
        if authorization_expires_at is not None
        else 2.0,
    )
    deadline = monotonic() + seconds
    if request_deadline is not None:
        if type(request_deadline) not in (int, float) or not isfinite(request_deadline):
            return ApiResponse(503, {"status": "task_preflight_unavailable", "retryable": False})
        deadline = min(deadline, request_deadline)

    def unavailable() -> ApiResponse:
        if authorization_expires_at is not None and datetime.now(UTC) >= authorization_expires_at:
            return ApiResponse(403, {"status": "forbidden", "reason": "host_grant_rejected"})
        return ApiResponse(503, {"status": "task_preflight_unavailable", "retryable": True})

    if seconds <= 0 or monotonic() >= deadline:
        return unavailable()
    result: T | ApiResponse
    try:
        with task_io_deadline(deadline):
            _check_read_deadline(deadline, authorization_expires_at)
            async with timeout(max(0, deadline - monotonic())):
                result = await read()
    except (TimeoutError, psycopg.OperationalError):
        return unavailable()
    except CheckpointNotReady:
        result = ApiResponse(409, {"status": "projection_not_ready", "retryable": True})
    except CheckpointConflict:
        result = ApiResponse(409, {"status": "projection_conflict", "retryable": False})
    # Check both clocks on every exit, including late typed projection errors.
    try:
        _check_read_deadline(deadline, authorization_expires_at)
    except TimeoutError:
        return unavailable()
    return result


def _check_read_deadline(deadline: float | None, expires_at: datetime | None) -> None:
    if deadline is not None and monotonic() >= deadline or (
        expires_at is not None and datetime.now(UTC) >= expires_at
    ):
        raise TimeoutError("Task preflight authorization deadline exceeded")


async def deadline_frames(
    source: AsyncGenerator[str, None],
    deadline: float,
    *,
    authorization_expires_at: datetime | None = None,
) -> AsyncIterator[str]:
    """Gate every frame, including after awaited IO and consumer backpressure."""

    def authorized() -> bool:
        return authorization_expires_at is None or datetime.now(UTC) < authorization_expires_at

    async with aclosing(source):
        while monotonic() < deadline and authorized():
            remaining = timeout(max(0, deadline - monotonic()))
            try:
                async with remaining:
                    frame = await anext(source)
            except StopAsyncIteration:
                return
            except TimeoutError:
                if remaining.expired():
                    return
                raise
            if monotonic() >= deadline or not authorized():
                return
            yield frame


def stream_problem(status: int, code: str, detail: str, path: str) -> ApiResponse:
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


def canonical_task_view(stores: ControlPlaneStores, task_id: TaskId) -> list[TaskEvent]:
    segments = sorted(stores.tasks.segments(task_id), key=lambda s: s.segment_index)
    if (
        not segments
        or str(segments[0].session_id) != str(task_id)
        or any(
            segment.task_id != task_id
            or segment.segment_index != index
            or segment.predecessor_id != (segments[index - 1].session_id if index else None)
            for index, segment in enumerate(segments)
        )
    ):
        raise AgUiProjectionError("Task membership is incomplete or contradictory")
    try:
        indexed = list(stores.tasks.read_events(task_id, -1))
    except ValueError as exc:
        raise AgUiProjectionError(str(exc)) from exc
    members = {segment.session_id for segment in segments}
    sequences: dict[object, int] = {}
    identities: set[object] = set()
    for position, item in enumerate(indexed):
        if (
            item.task_id != task_id
            or item.task_sequence != position
            or item.segment_id not in members
            or item.event.session_id != item.segment_id
            or item.event.sequence != item.segment_sequence
            or item.segment_sequence != sequences.get(item.segment_id, -1) + 1
            or item.event.event_id in identities
        ):
            raise AgUiProjectionError("canonical Task Event positions conflict")
        sequences[item.segment_id] = item.segment_sequence
        identities.add(item.event.event_id)
    positions = {item.event.event_id: item for item in indexed}
    identities.clear()
    for segment in segments:
        # ponytail: O(n) original read; an index high-watermark cannot prove an
        # intact prefix. Optimize only with verified prefix membership, not cache.
        for segment_sequence, event in enumerate(
            stores.events.list_for_session(segment.session_id)
        ):
            if (
                event.session_id != segment.session_id
                or event.sequence != segment_sequence
                or event.event_id in identities
            ):
                raise AgUiProjectionError("canonical Segment Event positions conflict")
            identities.add(event.event_id)
            if event.event_type is EventType.SESSION_HANDOFF_RECEIVED and (
                event.payload.get("root_session_id") != str(segments[0].session_id)
                or segment.predecessor_id is None
                or event.payload.get("parent_session_id") != str(segment.predecessor_id)
                or type(event.payload.get("stage_index")) is not int
                or event.payload["stage_index"] != segment.segment_index
            ):
                raise AgUiProjectionError("Task membership contradicts durable handoff origin")
            retained = positions.get(event.event_id)
            if retained is None or retained.event != event:
                raise AgUiProjectionError("Task index cannot align with canonical segment tails")
    if set(positions) != identities:
        raise AgUiProjectionError("Task index contains a non-member Segment")
    # Preserve canonical Task arrival order across Segment revisits; the retained
    # originals prove membership, not a new grouping that would change cursors.
    return indexed
