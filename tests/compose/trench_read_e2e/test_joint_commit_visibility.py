"""QA evidence guards; fixture Events test visibility, not live provider acceptance."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage.postgres.events import append_event_in_transaction
from joint_commit_visibility import (
    MAX_BYTES,
    MAX_EVENTS,
    ClockSample,
    CommitVisibilityProbe,
    calibrated_clock_interval,
    persisted_to_paint_interval,
    serve_probe,
)
from psycopg.rows import dict_row

from tests.agent_storage.test_postgres_command_wakeup import (
    NAMESPACE,
    _seed,
    dsn,  # noqa: F401 - reuse the isolated native migration fixture
    postgres_dsn,  # noqa: F401
)


def samples(remote="browser", offset=100):
    return [
        ClockSample("reference", remote, 10 + offset, 10, 12 + offset, 0),
        ClockSample("reference", remote, 90 + offset, 90, 92 + offset, 0),
    ]


def measurement():
    record = {
        "event_id": str(uuid4()),
        "task_sequence": 4,
        "turn_id": str(uuid4()),
        "output_id": "out:1",
        "status": "measured",
        "clock_id": "reference",
        "commit_interval_ms": [140, 150],
    }
    paint = {
        "eventId": record["event_id"],
        "sequence": 4,
        "turnId": record["turn_id"],
        "outputId": "out:1",
        "replay": False,
        "applied": True,
        "backgrounded": False,
        "relayReceivedAtMs": 55,
        "reactCommittedAtMs": 58,
        "paintReadyAtMs": 60,
    }
    return record, paint


def interval(record, paint, **kwargs):
    return persisted_to_paint_interval(
        record,
        paint,
        reference_clock_id="reference",
        browser_clock_id="browser",
        browser_samples=samples(),
        drift_ppm=0,
        **kwargs,
    )


def test_conservative_interval_uses_no_symmetric_delay_or_created_at():
    record, paint = measurement()
    record["created_at"] = "1900-01-01"
    result = interval(record, paint)
    assert result["interval_ms"] == [10, 22]
    assert result["endpoint"].endswith("not_physical_presentation")
    # Native Python and Node clocks require a second, independent mapping.
    record.update(clock_id="native", commit_interval_ms=[40, 50])
    assert interval(record, paint)["status"] == "invalid"
    assert interval(record, paint, commit_samples=samples("native"))["interval_ms"] == [8, 22]


@pytest.mark.parametrize(
    "field,value",
    [
        ("eventId", "relay:4"),
        ("sequence", True),
        ("turnId", "other"),
        ("outputId", "other"),
        ("replay", True),
        ("applied", False),
        ("backgrounded", True),
        ("coalesced", True),
        ("paintSuperseded", True),
        ("paintReadyAtMs", 57),
        ("paintReadyAtMs", float("nan")),
    ],
)
def test_invalid_identity_or_paint_remains_in_denominator(field, value):
    record, paint = measurement()
    paint[field] = value
    result = interval(record, paint)
    assert result["status"] == "invalid" and result["interval_ms"] is None
    assert result["event_id"] == record["event_id"]


def test_left_censored_is_retained_but_not_a_latency_pass():
    record, paint = measurement()
    record.update(status="left_censored", reason="no_prior_complete_absence_snapshot")
    result = interval(record, paint)
    assert result["status"] == "left_censored" and result["interval_ms"] is None
    paint["eventId"] = "relay:4"
    assert interval(record, paint)["status"] == "invalid"


@pytest.mark.parametrize("change", ["identity", "reset", "uncertainty", "unbracketed"])
def test_crossclock_rejects_unverified_calibration(change):
    values = samples()
    if change == "identity":
        values[1] = ClockSample("reference", "other", 190, 90, 192, 0)
    elif change == "reset":
        values[1] = ClockSample("reference", "browser", 190, 1, 192, 0)
    elif change == "uncertainty":
        values[1] = ClockSample("reference", "browser", 190, 90, 230, 0)
    else:
        values = values[:1]
    with pytest.raises(ValueError):
        calibrated_clock_interval(
            60,
            60,
            remote_clock_id="browser",
            reference_clock_id="reference",
            samples=values,
            drift_ppm=0,
        )


def mock_probe(monkeypatch, pages, *, floor=2):
    probe = CommitVisibilityProbe(
        "dbname=unused",
        deployment_namespace="probe",
        task_id=str(uuid4()),
        run_id="run",
        turn_id=str(uuid4()),
        after_sequence=floor,
    )
    database = MagicMock()
    database.deployment_namespace = "probe"
    probe.database = database
    header = SimpleNamespace(
        anchor=SimpleNamespace(event_id=uuid4()),
        control_only=False,
        start=3,
        stop=None,
        highwater=10,
    )
    monkeypatch.setattr("joint_commit_visibility.read_run_header", lambda *args: header)
    reader = MagicMock(side_effect=pages)
    monkeypatch.setattr("joint_commit_visibility.read_task_event_page", reader)
    return probe, reader


def page(sequence, *, highwater=10, more=False, events=(), size=1):
    return SimpleNamespace(
        events=events, byte_count=size, next_sequence=sequence, highwater=highwater, has_more=more
    )


def test_partial_page_is_not_a_miss_and_caps_are_cumulative(monkeypatch):
    event = SimpleNamespace(
        task_sequence=10,
        event=SimpleNamespace(
            event_id=uuid4(), event_type=EventType.PUBLIC_OUTPUT, payload={"output_id": "out:1"}
        ),
    )
    first = tuple(
        SimpleNamespace(event=SimpleNamespace(event_type=EventType.MODEL_REQUEST_STARTED))
        for _ in range(255)
    )
    probe, reader = mock_probe(
        monkeypatch,
        [
            page(9, more=True, events=first, size=MAX_BYTES - 10),
            page(10, events=(event,), size=10),
        ],
    )
    assert probe.poll()["status"] == "partial" and probe.absence is None
    hit = probe.poll()
    assert hit["records"][0]["status"] == "left_censored"
    assert reader.call_args.kwargs["limit"] == 1
    assert reader.call_args.kwargs["max_bytes"] == 10
    assert probe.poll()["reason"] == "per_run_event_or_byte_limit"
    assert probe.report()["events_read"] == MAX_EVENTS
    assert probe.report()["bytes_read"] == MAX_BYTES


def test_bad_floor_and_transport_errors_are_recorded_not_quietly_dropped(monkeypatch):
    probe, reader = mock_probe(monkeypatch, [], floor=3)
    assert probe.poll()["reason"] == "probe_floor_omits_run_window"
    reader.assert_not_called()
    assert len(probe.report()["observations"]) == 1
    probe, _ = mock_probe(monkeypatch, [RuntimeError("password=SECRET")])
    assert probe.poll()["reason"] == "native_probe_RuntimeError"
    assert "SECRET" not in str(probe.report())


def test_rpc_clock_identity_and_failures_are_bounded_and_sanitized(monkeypatch):
    probe, _ = mock_probe(monkeypatch, [])
    response = StringIO()
    serve_probe(
        probe,
        StringIO('{"request_id":"before","op":"clock"}\n{"request_id":"after","op":"clock"}\n'),
        response,
    )
    rows = [json.loads(line) for line in response.getvalue().splitlines()]
    assert [row["request_id"] for row in rows] == ["before", "after"]
    assert all(row["result"]["clock_id"] == probe.clock_id for row in rows)
    assert rows[0]["result"]["reading_ms"] <= rows[1]["result"]["reading_ms"]
    for request in ('{"request_id":"SECRET","op":"unknown"}\n', "SECRET" * 2000):
        response = StringIO()
        serve_probe(probe, StringIO(request), response)
        assert json.loads(response.getvalue())["status"] == "invalid"
        assert "SECRET" not in response.getvalue()


def test_rpc_ceiling_is_explicit_not_silent_eof(monkeypatch):
    probe, _ = mock_probe(monkeypatch, [])
    response = StringIO()
    serve_probe(probe, StringIO('{"request_id":"clock","op":"clock"}\n' * 4097), response)
    rows = [json.loads(line) for line in response.getvalue().splitlines()]
    assert len(rows) == 4097
    assert rows[-1] == {"status": "invalid", "reason": "probe_rpc_limit"}


def test_interval_rpc_reuses_crossclock_algorithm(monkeypatch):
    probe, _ = mock_probe(monkeypatch, [])
    record, paint = measurement()
    response = StringIO()
    arguments = dict(
        record=record,
        paint=paint,
        reference_clock_id="reference",
        browser_clock_id="browser",
        drift_ppm=0,
        browser_samples=[
            dict(
                reference_clock_id=row.reference_clock_id,
                remote_clock_id=row.remote_clock_id,
                send_ms=row.send_ms,
                remote_ms=row.remote_ms,
                return_ms=row.return_ms,
                precision_ms=row.precision_ms,
            )
            for row in samples()
        ],
    )
    serve_probe(
        probe,
        StringIO(
            json.dumps(dict(request_id="interval", op="interval", arguments=arguments)) + "\n"
        ),
        response,
    )
    result = json.loads(response.getvalue())
    assert result["request_id"] == "interval"
    assert result["result"]["interval_ms"] == [10, 22]


def test_cli_runs_rpc_with_private_inputs_and_no_credential_output(monkeypatch, tmp_path):
    from joint_commit_visibility import main

    probe, _ = mock_probe(monkeypatch, [])
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps({"TRENCH_E2E_BFF_URL": "http://localhost", "secret": "SECRET"}))
    path.chmod(0o600)
    factory = MagicMock(return_value=probe)
    monkeypatch.setattr("joint_commit_visibility.create_commit_probe", factory)
    monkeypatch.setattr("support.load_config", lambda *args: object())
    monkeypatch.setattr(
        "sys.argv",
        [
            "probe",
            "--inputs",
            str(path),
            "--task-id",
            "task",
            "--run-id",
            "run",
            "--turn-id",
            "turn",
            "--after-sequence",
            "2",
        ],
    )
    response = StringIO()
    monkeypatch.setattr("sys.stdout", response)
    monkeypatch.setattr("sys.stdin", StringIO('{"request_id":"initial","op":"clock"}\n'))
    assert main() == 0
    assert json.loads(response.getvalue())["result"]["clock_id"] == probe.clock_id
    factory.assert_called_once()
    assert "SECRET" not in response.getvalue()
    path.chmod(0o644)
    response.seek(0)
    response.truncate()
    assert main() == 2
    assert json.loads(response.getvalue())["reason"] == "probe_setup_ValueError"
    factory.assert_called_once()  # Reject permissions before parsing/wiring credentials.


@pytest.mark.parametrize("outcome", ["commit", "rollback", "left_censored"])
def test_native_uncommitted_miss_then_fresh_committed_hit(dsn, outcome):  # noqa: F811
    session = _seed(dsn)
    store_clock = iter(range(100, 200))
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        row = c.execute(
            "SELECT task_id,MAX(task_sequence) AS floor FROM session_events "
            "WHERE deployment_namespace=%s AND session_id=%s GROUP BY task_id",
            (NAMESPACE, session.session_id),
        ).fetchone()
        command = SessionCommand(
            session_id=session.session_id,
            kind=SessionCommandKind.RUN,
            expected_revision=row["floor"],
            idempotency_key="visibility-guard",
            payload={"run_id": "visibility-run"},
        )
        anchor = SessionEvent.create(
            session_id=session.session_id,
            sequence=row["floor"] + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
        )
        append_event_in_transaction(c, NAMESPACE, anchor)
    probe = CommitVisibilityProbe(
        dsn,
        deployment_namespace=NAMESPACE,
        task_id=str(row["task_id"]),
        run_id="visibility-run",
        turn_id=str(uuid4()),
        after_sequence=row["floor"],
        clock=lambda: next(store_clock),
    )
    if outcome != "left_censored":
        assert probe.poll()["status"] == "miss"
    output = SessionEvent.create(
        session_id=session.session_id,
        sequence=anchor.sequence + 1,
        event_type=EventType.PUBLIC_OUTPUT,
        actor=EventActor.SYSTEM,
        payload=dict(
            schema_version=1,
            attempt_number=1,
            output_id="out:visibility",
            kind="commentary",
            phase="evidence",
            origin="system",
            content="Fixture visibility.",
            status="complete",
        ),
        created_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    with psycopg.connect(dsn) as writer:
        append_event_in_transaction(writer, NAMESPACE, output)
        if outcome != "left_censored":
            assert probe.poll()["status"] == "miss"  # Writer has not committed.
            miss = deepcopy(probe.report()["observations"][-1])
        if outcome == "rollback":
            writer.rollback()
        else:
            writer.commit()
    observed = probe.poll()
    if outcome == "rollback":
        assert observed["status"] == "miss" and probe.report()["records"] == []
    else:
        record = observed["records"][0]
        assert record["event_id"] == str(output.event_id)
        assert "created_at" not in record
        if outcome == "commit":
            assert record["commit_interval_ms"] == [miss["send_ms"], observed["return_ms"]]
            assert record["miss_send_ms"] != miss["return_ms"]
        else:
            assert record["status"] == "left_censored" and record["commit_interval_ms"] is None
    # Namespace is part of the native query, not a client-side filter.
    wrong = CommitVisibilityProbe(
        dsn,
        deployment_namespace="other-namespace",
        task_id=str(row["task_id"]),
        run_id="visibility-run",
        turn_id=str(uuid4()),
        after_sequence=row["floor"],
    )
    assert wrong.poll()["status"] == "invalid"
