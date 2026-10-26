"""Original message coordinates cannot be inferred from a later Task head."""

from uuid import UUID, uuid4

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import new_idempotency_record
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.idempotency import request_hash

from tests.api.test_task_message_receipts import _snapshot
from tests.api.test_task_routes import _seed_completed

VERSION = "X-Zebra-Task-Message-Receipt-Version"


def _post(adapter, task, key, *, version="2", content="Continue the original message"):
    return adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task}/messages",
            body={"content": content},
            headers={"Idempotency-Key": key, VERSION: version},
        )
    )


def _read(adapter, task, key, version="2"):
    return adapter.handle(
        RouteRequest(
            "GET",
            f"/tasks/{task}/messages/receipt",
            headers={"Idempotency-Key": key, VERSION: version},
        )
    )


def _complete(app, segment):
    sid = SessionId(UUID(segment))
    events = list(app.stores.events.list_for_session(sid))
    for kind, payload in [
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "done"}),
        (EventType.SESSION_COMPLETED, {"summary": "done", "assistant_message": "done"}),
    ]:
        event = SessionEvent.create(
            session_id=sid,
            sequence=events[-1].sequence + 1,
            event_type=kind,
            actor=EventActor.HARNESS,
            payload=payload,
        )
        events.append(app.stores.events.append(event))
    app.stores.sessions.save_session(rebuild_session(events))


def test_coordinates_come_from_original_event_after_later_segment(tmp_path):
    database = tmp_path / "coordinates.sqlite"
    task = str(_seed_completed(database, tmp_path))
    app = create_app(database)
    adapter = RouteAdapter(app)
    key = str(uuid4())
    first = _post(adapter, task, key)
    assert first.status_code == 201
    coordinates = first.body["message_coordinates"]
    assert first.body["session_id"] == task
    assert coordinates["segment_id"] != task
    source = app.stores.events.list_for_session(SessionId(UUID(coordinates["segment_id"])))
    event = next(e for e in source if str(e.event_id) == coordinates["event_id"])
    assert event.session_id == UUID(coordinates["segment_id"])
    assert event.sequence == coordinates["segment_sequence"] == first.body["sequence"]
    # Actual execution may advance this Segment, but never relocates the original message.
    _complete(app, coordinates["segment_id"])
    same_head = adapter.handle(RouteRequest("GET", f"/tasks/{task}/header"))
    assert same_head.body["active_segment_id"] == coordinates["segment_id"]
    assert same_head.body["active_segment_sequence"] > coordinates["segment_sequence"]
    assert _read(adapter, task, key).body["message_coordinates"] == coordinates
    later = _post(adapter, task, str(uuid4()), content="Later independent follow-up")
    assert later.status_code == 201
    assert later.body["message_coordinates"]["segment_id"] != coordinates["segment_id"]
    app = create_app(database)
    adapter = RouteAdapter(app)
    _ = app.stores
    before = _snapshot(database)
    read = _read(adapter, task, key)
    assert read.status_code == 200 and read.body["contract_version"] == 2
    assert read.body["coordinates_status"] == "recorded"
    assert read.body["message_coordinates"] == coordinates
    assert read.body["response"] == {"status_code": 201, "body": first.body}
    assert _read(adapter, task, key, "1").body["response"]["body"] == first.body
    assert _snapshot(database) == before


def test_legacy_receipt_is_never_backfilled_or_reexecuted(tmp_path):
    database = tmp_path / "legacy.sqlite"
    task = str(_seed_completed(database, tmp_path))
    app = create_app(database)
    adapter = RouteAdapter(app)
    key = str(uuid4())
    original = _post(adapter, task, key, version="1")
    assert original.status_code == 201 and "message_coordinates" not in original.body
    before = _snapshot(database)
    replay = _post(adapter, task, key)
    assert replay.body == original.body
    observed = _read(adapter, task, key)
    assert observed.body["coordinates_status"] == "not_recorded"
    assert observed.body["message_coordinates"] is None
    assert observed.body["response"]["body"] == original.body
    assert _snapshot(database) == before


@pytest.mark.parametrize(
    "version,key",
    [
        ("3", "original"),
        ("0", "original"),
        ("02", "original"),
        ("2", ""),
        ("2", "x" * 129),
        ("2", "bad key"),
    ],
)
def test_invalid_negotiation_fails_before_rollover(version, key, tmp_path):
    database = tmp_path / "invalid.sqlite"
    task = str(_seed_completed(database, tmp_path))
    app = create_app(database)
    _ = app.stores
    adapter = RouteAdapter(app)
    before = _snapshot(database)
    result = _post(adapter, task, key, version=version)
    assert result.status_code == 400
    assert _snapshot(database) == before


@pytest.mark.parametrize(
    "bad",
    [
        {"event_id": "wrong"},
        {"event_id": str(uuid4()), "segment_id": str(uuid4()), "segment_sequence": True},
        {"event_id": str(uuid4()), "segment_id": str(uuid4()), "segment_sequence": -1},
        {"event_id": str(uuid4()), "segment_id": str(uuid4()), "segment_sequence": 99},
    ],
)
def test_invalid_saved_coordinate_is_unknown_not_current_head(bad, tmp_path):
    app = create_app(tmp_path / "tamper.sqlite")
    adapter = RouteAdapter(app)
    task, key = str(uuid4()), str(uuid4())
    body = {"sequence": 2, "current_sequence": 2, "message_coordinates": bad}
    app.stores.idempotency.save(
        new_idempotency_record(
            action=f"task-message:{task}",
            idempotency_key=key,
            request_hash=request_hash({"content": "original"}),
            status_code=201,
            response_body=body,
        )
    )
    result = _read(adapter, task, key)
    assert (
        result.body["coordinates_status"] == "invalid"
        and result.body["message_coordinates"] is None
    )
    assert result.body["response"]["body"] == body
