from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_artifact_history import artifact_segments, route_task_artifact


def test_historical_selection_requires_primary_task_membership():
    task, segment, foreign = uuid4(), uuid4(), uuid4()
    store = Mock()
    stores = SimpleNamespace(tasks=store)
    handler = Mock(return_value=ApiResponse(200, {"artifacts": []}))
    store.task_id_for_session.return_value = foreign
    assert (
        route_task_artifact(stores, str(task), {"segment_id": str(segment)}, handler).status_code
        == 404
    )
    handler.assert_not_called()
    store.task_id_for_session.return_value = task
    result = route_task_artifact(stores, str(task), {"segment_id": str(segment)}, handler)
    assert result.status_code == 200
    assert result.body["source_segment_id"] == str(segment)
    assert result.body["session_id"] == str(task)
    handler.assert_called_once_with(str(segment))
    store.segments.assert_not_called()


def test_current_segment_remains_default():
    task, segment = uuid4(), uuid4()
    store = Mock()
    store.active_segment.return_value = segment
    handler = Mock(return_value=ApiResponse(200, {}))
    assert (
        route_task_artifact(SimpleNamespace(tasks=store), str(task), {}, handler).status_code == 200
    )
    store.task_id_for_session.assert_not_called()


@pytest.mark.parametrize(
    "query", [{"after": "-2"}, {"limit": "101"}, {"limit": "1.2"}, {"after": "NaN"}]
)
def test_page_rejects_unbounded_or_invalid_coordinates(query):
    store = Mock()
    assert artifact_segments(SimpleNamespace(tasks=store), str(uuid4()), query).status_code == 400
    store.segment_page.assert_not_called()


def test_page_uses_bounded_lookahead_and_stable_cursor():
    task = uuid4()
    store = Mock()
    store.get_task.return_value = SimpleNamespace(active_segment_id=uuid4())
    store.segment_page.return_value = tuple(
        SimpleNamespace(session_id=uuid4(), segment_index=i) for i in range(4, 7)
    )
    result = artifact_segments(
        SimpleNamespace(tasks=store), str(task), {"after": "3", "limit": "2"}
    )
    store.segment_page.assert_called_once_with(task, after_index=3, limit=3)
    assert result.body["has_more"] is True
    assert result.body["next_after"] == 5
    assert len(result.body["segments"]) == 2
