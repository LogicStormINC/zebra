"""Observation-only bounded SSE tail of shared durable projection checkpoints."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from random import uniform
from time import monotonic
from typing import TYPE_CHECKING

from ag_ui.core import CustomEvent
from ag_ui.encoder import EventEncoder
from agent_core.ports.live_event_fanout import CheckpointNotificationPort, LiveEventCursor
from agent_core.ports.stream_source_head import StreamSourceHeadPort
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_projection_work import ProjectionWorkProblem
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_storage.postgres.task_io import task_io_deadline

if TYPE_CHECKING:
    from zebra_agent_api.ag_ui_stream import AgUiStreamContext, _DisconnectableRequest

logger = logging.getLogger(__name__)


async def _read_until[**P, R](
    deadline: float, read: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    def bounded() -> R:
        # Independent connections in one read share its budget; never scope a consumer yield.
        with task_io_deadline(min(deadline, monotonic() + 2.0)):
            return read(*args, **kwargs)

    return await asyncio.to_thread(bounded)


def observation_problem(code: str, *, retryable: bool) -> str:
    # This is a transport observation, not a canonical RunError/Task transition.
    return EventEncoder().encode(
        CustomEvent(
            name="zebra.observation.problem",
            value={"code": code, "retryable": retryable},
        )
    )


def projection_problem_notice(problem: ProjectionWorkProblem) -> tuple[str, bool] | None:
    """Transport classification only; dependency wait never becomes Task failure."""
    if problem.code == "not_ready":
        return None
    if problem.code == "integrity":
        return "projection_conflict", False
    if problem.code == "budget":
        return "projection_budget_exceeded", False
    if problem.retry_at is None:
        return "observation_unavailable", False
    return "projection_retry_scheduled", True


async def _checkpoint_barrier(
    context: AgUiStreamContext, deadline: float
) -> LiveEventCursor | None:
    fanout = context.live_event_fanout
    notifications = getattr(context, "notifications", None)
    if notifications is not None and context.deployment_namespace is not None:
        key = notifications.key(context.deployment_namespace, context.task_id, checkpoint=True)
        try:
            return LiveEventCursor(await notifications.barrier(key), stream_ref=key)
        except Exception:
            return None
    if not isinstance(fanout, CheckpointNotificationPort) or context.deployment_namespace is None:
        return None
    try:
        return await _read_until(
            deadline,
            fanout.capture_checkpoint_barrier,
            deployment_namespace=context.deployment_namespace,
            task_id=context.task_id,
        )
    except Exception:
        return None


async def _backoff_slice(deadline: float, retry_at: float, keepalive_seconds: float) -> bool:
    """Yield control for heartbeats without advancing the SQL/Redis retry frontier."""
    await asyncio.sleep(
        min(
            max(0.0, retry_at - monotonic()),
            max(0.001, keepalive_seconds),
            max(0.0, deadline - monotonic()),
        )
    )
    return monotonic() >= retry_at


async def _checkpoint_wait(
    context: AgUiStreamContext,
    deadline: float,
    barrier: LiveEventCursor | None,
    poll_seconds: float,
    backoff: float,
    keepalive_seconds: float,
    retry_at: float | None,
) -> tuple[LiveEventCursor | None, float | None, bool]:
    fanout = context.live_event_fanout
    if retry_at is None:
        notifications = getattr(context, "notifications", None)
        if barrier is not None and notifications is not None:
            assert barrier.stream_ref is not None
            positions = await notifications.wait(
                {barrier.stream_ref: barrier.value},
                block_ms=max(1, int(min(1, deadline - monotonic(), keepalive_seconds) * 1000)),
            )
            return (
                LiveEventCursor(positions[barrier.stream_ref], stream_ref=barrier.stream_ref),
                None,
                False,
            )
        if (
            barrier is not None
            and isinstance(fanout, CheckpointNotificationPort)
            and context.deployment_namespace is not None
        ):
            try:
                cursor = await _read_until(
                    deadline,
                    fanout.wait_checkpoint_after,
                    deployment_namespace=context.deployment_namespace,
                    task_id=context.task_id,
                    barrier=barrier,
                    block_ms=max(
                        1, int(min(1.0, deadline - monotonic(), keepalive_seconds) * 1000)
                    ),
                )
                return cursor, None, False
            except Exception:
                pass
        # Cloud readers reconcile even after a missed readiness publication.
        cloud = (
            context.deployment_namespace not in {None, "local"}
            or getattr(context.stores, "deployment_namespace", None) is not None
        )
        delay = min(30.0, backoff * uniform(0.9, 1.1)) if cloud else poll_seconds
        retry_at = monotonic() + delay
    if not await _backoff_slice(deadline, retry_at, keepalive_seconds):
        return None, retry_at, False
    return await _checkpoint_barrier(context, deadline), None, True


async def tail_checkpoint_frames(
    context: AgUiStreamContext,
    request: _DisconnectableRequest,
    deadline: float,
    *,
    poll_seconds: float,
    keepalive_seconds: float,
) -> AsyncGenerator[str, None]:
    observer = AgUiCheckpointObserver(
        context.stores.tasks,
        namespace=context.deployment_namespace or "local",
        profile=getattr(context, "profile", None),
    )
    barrier = await _checkpoint_barrier(context, deadline)  # Before snapshot/replay.
    cursor, after_source = context.cursor, None
    backoff, retry_at = 1.0, None
    recovered = not getattr(context, "recovery_notice", False)
    reported_problem: ProjectionWorkProblem | None = None
    encoder, last_delivery, failures = EventEncoder(), monotonic(), 0
    while monotonic() < deadline:
        if await request.is_disconnected():
            return
        emitted = False
        try:
            compatible = getattr(
                getattr(context, "command_outcome", None), "supports_source_head", None
            )
            captured_host = (
                context.host_context
                if callable(compatible) and compatible(context.stores.tasks)
                else None
            )
            snapshot = await _read_until(
                deadline,
                observer.snapshot,
                context.task_id,
                context.identity,
                *((captured_host,) if captured_host is not None else ()),
            )
            if monotonic() >= deadline or await request.is_disconnected():
                return
            if snapshot.run.control_only:
                yield observation_problem("not_executable_run", retryable=False)
                return
            command_pending = context.command_outcome is not None and snapshot.run.anchor is None
            if snapshot.bound and not command_pending:
                if after_source is None:
                    await _read_until(
                        deadline, observer.validate_cursor, snapshot, context.identity, cursor
                    )
                    after_source = (
                        snapshot.run.start - 1
                        if cursor is None
                        else cursor.sequence - (1 if cursor.frame_index is not None else 0)
                    )
                page = await _read_until(deadline, observer.read_page, snapshot, after_source)
                if page is not None:
                    if getattr(context.stores, "deployment_namespace", None) is not None:
                        if isinstance(context.stores.tasks, StreamSourceHeadPort) and getattr(
                            context.stores.tasks, "stream_head_reads_compatible", True
                        ):
                            source = await _read_until(
                                deadline,
                                context.stores.tasks.read_stream_source_head,
                                task_id=context.task_id,
                            )
                            header = source.task if source is not None else None
                        else:
                            header = await _read_until(
                                deadline,
                                context.stores.tasks.read_task_header,
                                context.task_id,
                                require_source_coverage=True,
                            )
                        if (
                            header is None
                            or header.strict_coverage is None
                            or (header.strict_coverage != snapshot.run.strict_coverage)
                        ):
                            raise CheckpointConflict("public replay source privacy changed")
                    # At most one bounded Page is retained; frames encode/yield lazily.
                    frames = observer.iter_page_frames(
                        snapshot, page, context.identity, after=cursor
                    )
                    while True:
                        if monotonic() >= deadline or await request.is_disconnected():
                            return
                        frame = await _read_until(deadline, next, frames, None)
                        if frame is None:
                            break
                        next_cursor, event = frame
                        if monotonic() >= deadline or await request.is_disconnected():
                            return
                        cursor, emitted, last_delivery = next_cursor, True, monotonic()
                        yield f"id: {cursor.encode()}\n{encoder.encode(event)}"
                    after_source = page.next_sequence  # Include zero-frame source rows.
                target = (
                    snapshot.run.highwater if snapshot.run.stop is None else snapshot.run.stop - 1
                )
                if not recovered and after_source >= target and snapshot.through >= target:
                    recovered = True
                    yield EventEncoder().encode(
                        CustomEvent(name="zebra.stream.recovery_complete", value={})
                    )
                terminal = snapshot.head.terminal
                if (
                    terminal is not None
                    and terminal.task_sequence <= snapshot.through
                    and (after_source >= terminal.task_sequence)
                ):
                    return
                if snapshot.run.stop is not None and after_source >= snapshot.run.stop - 1:
                    return
                target = (
                    snapshot.run.highwater if snapshot.run.stop is None else snapshot.run.stop - 1
                )
                work = (
                    context.stores.coverage_projection_work
                    if snapshot.run.strict_coverage
                    else context.stores.projection_work
                )
                if getattr(context, "profile", None) is not None:
                    factory = context.stores.projection_work_for_version
                    if factory is None:
                        raise ValueError("profile projection work reader is not bound")
                    work = factory(snapshot.head.scope.projector_version)
                if (
                    snapshot.run.anchor is not None
                    and work is not None
                    and snapshot.through < target
                    and after_source >= snapshot.through
                ):
                    problem = await _read_until(
                        deadline, work.read_projection_work_problem, snapshot.head.scope
                    )
                    if monotonic() >= deadline or await request.is_disconnected():
                        return
                    if problem is not None and problem.scope != snapshot.head.scope:
                        raise ValueError("projection problem belongs to another canonical scope")
                    if problem != reported_problem:
                        reported_problem = problem  # One notice per state, not per polling tick.
                        notice = projection_problem_notice(problem) if problem is not None else None
                        if notice is not None:
                            code, retryable = notice
                            emitted, last_delivery = True, monotonic()
                            yield observation_problem(code, retryable=retryable)
                            if not retryable:
                                return
                if (
                    context.command_outcome is not None
                    and context.host_context is not None
                    and snapshot.run.anchor is not None
                ):
                    outcome = snapshot.command_outcome
                    if not snapshot.outcome_checked:
                        outcome = await _read_until(
                            deadline,
                            context.command_outcome,
                            context.task_id,
                            context.identity.run_id,
                            snapshot.run.anchor.event_id,
                            context.host_context,
                        )
                    if monotonic() >= deadline or await request.is_disconnected():
                        return
                    if outcome in {
                        "command_requires_reconciliation",
                        "command_unsupported",
                        "command_recovery_exhausted",
                        "command_delivery_failed",
                    }:
                        yield observation_problem(outcome, retryable=False)
                        return
            failures = 0
        except CheckpointNotReady:
            # Materialization happens outside this connection. Never backfill here.
            pass
        except ValueError:
            if monotonic() >= deadline or await request.is_disconnected():
                return
            yield observation_problem("projection_conflict", retryable=False)
            return
        except Exception as exc:
            if monotonic() >= deadline or await request.is_disconnected():
                return
            failures += 1
            logger.warning("AG-UI observation read failed: %s", type(exc).__name__)
            if failures >= 20:
                yield observation_problem("observation_unavailable", retryable=True)
                return
        if monotonic() >= deadline or await request.is_disconnected():
            return
        if not emitted and monotonic() - last_delivery >= keepalive_seconds:
            last_delivery = monotonic()
            yield ": keepalive\n\n"
        if not emitted:
            reconcile_at = monotonic() + 30.0
            while monotonic() < deadline:
                previous = barrier
                barrier, retry_at, reconcile = await _checkpoint_wait(
                    context,
                    deadline,
                    barrier,
                    poll_seconds,
                    backoff,
                    max(0.001, keepalive_seconds - monotonic() + last_delivery),
                    retry_at,
                )
                if retry_at is None:
                    backoff = min(30.0, backoff * 2) if reconcile else 1.0
                if (
                    reconcile
                    or retry_at is None
                    and barrier != previous
                    or monotonic() >= reconcile_at
                ):
                    break
                if await request.is_disconnected():
                    return
                if monotonic() - last_delivery >= keepalive_seconds:
                    last_delivery = monotonic()
                    yield ": keepalive\n\n"
