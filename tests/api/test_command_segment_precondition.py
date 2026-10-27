"""Original Segment preconditions must fail before writing or following current rollover."""
from uuid import uuid4

from agent_storage import SQLiteEventStore
from zebra_agent_api.routes import RouteRequest

from tests.api.test_agui_bound_client_state import setup_surface


def test_original_segment_precondition_before_admission(tmp_path):
    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    before = SQLiteEventStore(db).list_for_session(task)
    for segment, expected in [("invalid", 400), (str(uuid4()), 409)]:
        response = adapter.handle(RouteRequest(
            "POST", "/agui/commands", body=body,
            headers={**headers, "X-Zebra-Command-Segment": segment},
        ))
        assert response.status_code == expected
        assert SQLiteEventStore(db).list_for_session(task) == before
    response = adapter.handle(RouteRequest(
        "POST", "/agui/commands", body=body,
        headers={**headers, "X-Zebra-Command-Segment": str(task)},
    ))
    assert response.status_code == 202
    assert len(SQLiteEventStore(db).list_for_session(task)) == len(before) + 1
