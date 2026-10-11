"""Full canonical Task identity must survive incremental SSE slicing."""

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui.contracts import AgUiCursor
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from zebra_agent_api.ag_ui_stream import _project_new_task_events

from tests.agent_integrations.test_ag_ui_coverage_projection import stream
from tests.agent_integrations.test_coverage_public_events import event


def view(payload):
    _, identity = stream()
    task = TaskId(identity.session_id)
    identity = identity.model_copy(update={"thread_id": str(task)})
    rows = (
        event(EventType.MODEL_RESPONSE_RECEIVED, 0,
              {"assistant_message": "PRIVATE_PREFIX_CANDIDATE"}, identity.session_id),
        event(EventType.TASK_PREPARED, 1, payload, identity.session_id),
    )
    return identity, tuple(
        TaskEvent(task, i, row.session_id, row.sequence, row) for i, row in enumerate(rows)
    )


@pytest.mark.parametrize("marker", [None, {}, "invalid"])
@pytest.mark.parametrize("reconnect", [False, True])
def test_late_strict_marker_hides_earlier_response_across_sse_prefixes(marker, reconnect):
    identity, rows = view({"title": "strict", "coverage_admission": marker})
    after = None if not reconnect else AgUiCursor(
        thread_id=identity.thread_id, run_id=identity.run_id,
        sequence=0, event_id=str(rows[0].event.event_id),
    )
    assert "PRIVATE_PREFIX_CANDIDATE" not in str(
        AgUiTaskProjector().project_task(rows, identity, after=after).events
    )
    frames = _project_new_task_events(rows, identity, after)
    assert "PRIVATE_PREFIX_CANDIDATE" not in "".join(frame for _, frame in frames)


def test_ordinary_prefix_still_publishes_response():
    identity, rows = view({"title": "ordinary"})
    frames = _project_new_task_events(rows, identity, None)
    assert "PRIVATE_PREFIX_CANDIDATE" in "".join(frame for _, frame in frames)


def test_false_override_cannot_disable_strict_identity():
    identity, rows = view({"title": "strict", "coverage_admission": None})
    assert "PRIVATE_PREFIX_CANDIDATE" not in str(
        AgUiTaskProjector().project_task(rows, identity, strict_coverage=False).events
    )
