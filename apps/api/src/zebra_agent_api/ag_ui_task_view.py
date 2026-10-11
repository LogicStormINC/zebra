"""Read-only canonical tail overlay for initial replay and rollover refresh."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from time import monotonic

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui import AgUiProjectionError
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse


async def deadline_frames(source: AsyncGenerator[str, None], deadline: float) -> AsyncIterator[str]:
    """Gate every frame, including after awaited IO and consumer backpressure."""
    async with aclosing(source):
        while monotonic() < deadline:
            try:
                frame = await anext(source)
            except StopAsyncIteration:
                return
            if monotonic() >= deadline:
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
    indexed = stores.tasks.read_events(task_id, -1)
    positions = {str(e.event.event_id): e.task_sequence for e in indexed}
    result: list[TaskEvent] = []
    for segment in segments:
        # ponytail: O(n) original read; an index high-watermark cannot prove an
        # intact prefix. Optimize only with verified prefix membership, not cache.
        for event in stores.events.list_for_session(segment.session_id):
            if event.event_type is EventType.SESSION_HANDOFF_RECEIVED and (
                event.payload.get("root_session_id") != str(segments[0].session_id)
                or segment.predecessor_id is None
                or event.payload.get("parent_session_id") != str(segment.predecessor_id)
                or type(event.payload.get("stage_index")) is not int
                or event.payload["stage_index"] != segment.segment_index
            ):
                raise AgUiProjectionError("Task membership contradicts durable handoff origin")
            sequence = len(result)
            if positions.get(str(event.event_id), sequence) != sequence:
                # Never change an emitted cursor to point at a different Event.
                raise AgUiProjectionError("Task index cannot align with canonical segment tails")
            result.append(TaskEvent(task_id, sequence, segment.session_id, event.sequence, event))
    if not set(positions).issubset(str(e.event.event_id) for e in result):
        raise AgUiProjectionError("Task index contains a non-member Segment")
    return result
