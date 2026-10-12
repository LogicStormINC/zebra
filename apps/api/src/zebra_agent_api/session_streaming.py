from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from random import uniform
from time import monotonic

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import LiveEventCursor, LiveEventFanoutPort
from agent_storage import ControlPlaneStores, sqlite_control_plane_stores
from fastapi import Request

from zebra_agent_api.ag_ui_checkpoint_tail import _backoff_slice, _read_until
from zebra_agent_api.ag_ui_task_view import canonical_task_view, deadline_frames
from zebra_agent_api.coverage_public_read import (
    coverage_public_read_problem,
    coverage_session_read_problem,
)
from zebra_agent_api.task_api import is_user_task_event, serialize_task_event

_POLL_SECONDS = 0.05
_KEEPALIVE_SECONDS = 15.0
_FALLBACK_SECONDS = 1.0
_MAX_STREAM_SECONDS = 1800.0
# awaiting_turn keeps a conversation Task stream open between Turns (ADR-026).
_ACTIVE_STATUSES = frozenset(
    {SessionStatus.READY, SessionStatus.RUNNING, SessionStatus.AWAITING_TURN}
)


class StreamWake:
    """Barrier before replay; Redis only wakes a fresh authoritative read.

    ponytail: synchronous blocking reads occupy the default executor (up to 32
    threads). Async Redis notifications or bounded instance fan-out are the
    upgrade path before claiming the 100-subscriber latency gate.
    """

    def __init__(
        self, fanout: LiveEventFanoutPort | None, namespace: str | None,
        session_id: SessionId, deadline: float, *, cloud: bool = False,
    ) -> None:
        self.fanout, self.namespace, self.session_id = fanout, namespace, session_id
        self.deadline = deadline
        self.cloud = cloud or namespace not in {None, "local"}
        self.cursor: LiveEventCursor | None = None
        self.retry_at = 0.0
        self.fallback_until: float | None = None
        self.backoff = 1.0
        self.reconcile_at = monotonic() + 30.0

    async def capture(self) -> None:
        if self.fanout is None or self.namespace is None or monotonic() < self.retry_at:
            return
        try:
            self.cursor = await _read_until(
                self.deadline, self.fanout.capture_barrier,
                deployment_namespace=self.namespace, session_id=self.session_id,
            )
        except Exception:
            self.cursor, self.retry_at = None, monotonic() + _FALLBACK_SECONDS

    async def _wait_backoff(self, keepalive_seconds: float) -> bool:
        assert self.fallback_until is not None
        ready = await _backoff_slice(self.deadline, self.fallback_until, keepalive_seconds)
        if ready:
            self.fallback_until = None
        return ready

    async def wait(
        self, sequence: int, *, keepalive_seconds: float = _KEEPALIVE_SECONDS
    ) -> bool:
        if self.fallback_until is not None:
            return await self._wait_backoff(keepalive_seconds)
        if self.cursor is None:
            await self.capture()
        if self.cursor is not None and self.fanout is not None and self.namespace is not None:
            try:
                batch = await _read_until(
                    self.deadline, self.fanout.read_after,
                    deployment_namespace=self.namespace, session_id=self.session_id,
                    barrier=self.cursor, durable_sequence=sequence, count=100,
                    block_ms=max(1, int(
                        min(1.0, self.deadline - monotonic(), keepalive_seconds) * 1000
                    )),
                )
                changed = self.cursor != batch.next_cursor
                self.cursor, self.backoff = batch.next_cursor, 1.0
                if changed or monotonic() >= self.reconcile_at:
                    self.reconcile_at = monotonic() + 30.0
                    return True
                return False
            except Exception:
                self.cursor, self.retry_at = None, monotonic() + _FALLBACK_SECONDS
        # ponytail: bounded degraded polling also recovers lost/trimmed Redis hints.
        delay = min(30.0, self.backoff * uniform(0.9, 1.1)) if self.cloud else _POLL_SECONDS
        self.backoff = min(30.0, self.backoff * 2)
        self.retry_at = self.fallback_until = monotonic() + delay
        return await self._wait_backoff(keepalive_seconds)


def _deadline(expires_at: datetime | None) -> float:
    if expires_at is None:
        return float("inf")  # Preserve indefinite local/conversation observation.
    seconds = max(
        0.0, (expires_at - datetime.now(UTC)).total_seconds()
    )
    return monotonic() + min(seconds, _MAX_STREAM_SECONDS)


async def tail_session_events(
    *, database_path: Path, stores: ControlPlaneStores | None = None,
    live_event_fanout: LiveEventFanoutPort | None = None,
    deployment_namespace: str | None = None, session_id: SessionId,
    request: Request, after_sequence: int,
    authorization_expires_at: datetime | None = None,
) -> AsyncIterator[str]:
    active = stores or sqlite_control_plane_stores(database_path)
    deadline = _deadline(authorization_expires_at)

    async def frames() -> AsyncGenerator[str, None]:
        wake = StreamWake(
            live_event_fanout, deployment_namespace, session_id, deadline,
            cloud=getattr(active, "deployment_namespace", None) is not None,
        )
        await wake.capture()  # Capture before either privacy preflight or durable replay.
        if await _read_until(deadline, coverage_session_read_problem, active, session_id):
            return
        cursor, closing, last_delivery = after_sequence, False, monotonic()
        while not await request.is_disconnected():
            events = await _read_until(deadline, active.events.read_since, session_id, cursor)
            if coverage_public_read_problem(events):
                return
            for event in events:
                cursor, last_delivery = event.sequence, monotonic()
                yield encode_sse_event(event)
            if events:
                continue
            if closing:
                return
            session = await _read_until(deadline, active.sessions.get_session, session_id)
            if session is None or session.status not in _ACTIVE_STATUSES:
                # Terminal can commit between the empty read and status read.
                # Drain again AFTER observing terminal, then close on an empty suffix.
                closing = True
                continue
            if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
                last_delivery = monotonic()
                yield ": keepalive\n\n"
            while not await wake.wait(
                cursor, keepalive_seconds=max(
                    0.001, _KEEPALIVE_SECONDS - monotonic() + last_delivery
                )
            ):
                if await request.is_disconnected():
                    return
                if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
                    last_delivery = monotonic()
                    yield ": keepalive\n\n"

    async for frame in deadline_frames(
        frames(), deadline, authorization_expires_at=authorization_expires_at
    ):
        yield frame


async def tail_task_events(
    *, database_path: Path, stores: ControlPlaneStores | None = None,
    task_id: TaskId, request: Request, after_sequence: int,
    live_event_fanout: LiveEventFanoutPort | None = None,
    deployment_namespace: str | None = None,
    authorization_expires_at: datetime | None = None,
) -> AsyncIterator[str]:
    active = stores or sqlite_control_plane_stores(database_path)
    store, deadline = active.tasks, _deadline(authorization_expires_at)

    async def frames() -> AsyncGenerator[str, None]:
        task = await _read_until(deadline, store.get_task, task_id)
        if task is None:
            return
        wake = StreamWake(
            live_event_fanout, deployment_namespace, task.active_segment_id, deadline,
            cloud=getattr(active, "deployment_namespace", None) is not None,
        )
        await wake.capture()
        view = await _read_until(deadline, canonical_task_view, active, task_id)
        if coverage_public_read_problem(item.event for item in view):
            return
        del view
        cursor, closing, last_delivery = after_sequence, False, monotonic()
        while not await request.is_disconnected():
            page = await _read_until(deadline, store.read_event_page, task_id, cursor)
            events = page.events
            if coverage_public_read_problem(item.event for item in events):
                return
            for event in events:
                cursor = event.task_sequence
                if not is_user_task_event(event):
                    continue
                last_delivery = monotonic()
                yield (
                    f"id: {event.task_sequence}\n"
                    "event: task_event\n"
                    f"data: {json.dumps(serialize_task_event(event), sort_keys=True)}\n\n"
                )
            if events:
                continue
            if closing:
                return
            task = await _read_until(deadline, store.get_task, task_id)
            if task is None or task.status not in _ACTIVE_STATUSES:
                closing = True
                continue
            if task.active_segment_id != wake.session_id:
                wake = StreamWake(
                    live_event_fanout, deployment_namespace, task.active_segment_id, deadline,
                    cloud=getattr(active, "deployment_namespace", None) is not None,
                )
                await wake.capture()
                continue  # Replay again after capturing the new Segment barrier.
            if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
                last_delivery = monotonic()
                yield ": keepalive\n\n"
            # Task and Segment cursors differ; consume hints without a Task cursor filter.
            while not await wake.wait(
                -1, keepalive_seconds=max(0.001, _KEEPALIVE_SECONDS - monotonic() + last_delivery)
            ):
                if await request.is_disconnected():
                    return
                if monotonic() - last_delivery >= _KEEPALIVE_SECONDS:
                    last_delivery = monotonic()
                    yield ": keepalive\n\n"

    async for frame in deadline_frames(
        frames(), deadline, authorization_expires_at=authorization_expires_at
    ):
        yield frame


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
