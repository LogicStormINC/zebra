"""Small runnable guard for the profiler's easily inflated SQL metric."""

import pytest

from tests.stream_storage.telemetry import _INSIDE, Telemetry, category


def test_nested_connection_cursor_call_counts_once_and_resets_after_failure():
    telemetry = Telemetry()

    def nested():
        assert _INSIDE.get()
        # Installed Cursor wrapper delegates directly during Connection.execute.
        return 42

    assert telemetry.measured("SELECT 1", nested) == 42
    assert sum(v for k, v in telemetry.calls.items() if "/sql:" in k) == 1
    assert not _INSIDE.get()
    try:
        telemetry.measured("SELECT 1", lambda: (_ for _ in ()).throw(ValueError()))
    except ValueError:
        pass
    assert sum(v for k, v in telemetry.calls.items() if "/sql:" in k) == 2 and not _INSIDE.get()
    assert category("SELECT secret FROM session_events WHERE payload=%s") == "event"
    assert "secret" not in str(telemetry.report())


def test_native_connection_and_cursor_count_two_not_three():
    import os

    import psycopg

    dsn = os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("native SQL counter control needs disposable PostgreSQL")
    telemetry = Telemetry()
    with psycopg.connect(dsn, autocommit=True) as connection, telemetry.installed():
        assert connection.execute("SELECT 1").fetchone() == (1,)
        with connection.cursor() as cursor:
            assert cursor.execute("SELECT 2").fetchone() == (2,)
    assert sum(v for k, v in telemetry.calls.items() if "/sql:" in k) == 2


def test_empty_pool_check_query_is_counted_without_changing_behavior():
    telemetry = Telemetry()
    assert telemetry.measured("", lambda: "pool_check") == "pool_check"
    assert sum(v for k, v in telemetry.calls.items() if "/sql:" in k) == 1


def test_socket_generator_preserves_yield_return_and_failed_attempt(monkeypatch):
    import psycopg

    def connect(cls, *, fail=False):
        received = yield "driver_wait"
        assert received == "ready"
        if fail:
            raise ValueError("connect failed")
        return "connection"

    monkeypatch.setattr(psycopg.Connection, "_connect_gen", classmethod(connect))
    telemetry = Telemetry()
    with telemetry.installed():
        successful = psycopg.Connection._connect_gen()
        assert next(successful) == "driver_wait"
        with pytest.raises(StopIteration) as returned:
            successful.send("ready")
        assert returned.value.value == "connection"
        failed = psycopg.Connection._connect_gen(fail=True)
        assert next(failed) == "driver_wait"
        with pytest.raises(ValueError, match="connect failed"):
            failed.send("ready")
    assert telemetry.calls["initial/setup/new_pg_socket"] == 1
    assert telemetry.calls["initial/setup/pg_connect_attempt"] == 2
    assert telemetry.connect_seconds["initial/setup/pg_connect"] > 0
    assert not telemetry.seconds


def test_asgi_diagnostics_preserve_group_and_cancellation_without_secret_strings():
    import asyncio
    import threading
    from types import SimpleNamespace

    from tests.stream_storage.native_source_head_diagnostics import (
        capture_asgi_exception,
        failure_diagnostics,
    )

    error = BaseExceptionGroup(
        "private sentinel",
        [TimeoutError("private timeout"), ValueError(), asyncio.CancelledError()],
    )
    records, messages, lock = [], [], threading.Lock()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "more_body": True, "body": b"private"})
        raise error

    async def send(message):
        messages.append(message["type"])

    with pytest.raises(BaseExceptionGroup) as raised:
        asyncio.run(capture_asgi_exception(app, {}, None, send, records, lock))
    assert raised.value is error and messages == ["http.response.start", "http.response.body"]
    assert records[0]["phase"] == "streaming"
    assert records[0]["leaf_classes"] == ["TimeoutError", "ValueError"]
    assert records[0]["entered"] <= records[0]["last_send"] <= records[0]["raised"]
    assert "private" not in str(records)
    error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError) as cancelled:
        asyncio.run(capture_asgi_exception(app, {}, None, send, records, lock))
    assert cancelled.value is error and len(records) == 1
    state = SimpleNamespace(
        steady_started=10.0,
        steady_ended=None,
        observation_exited=13.0,
        completed_lease_heartbeats=1,
        admitted=[True],
        recovered=[True],
        admission_errors=[],
        read_timings={},
        admission_timings=records,
    )
    failure = failure_diagnostics(state, Telemetry(), 600)
    assert failure["scheduled_steady_end"] == 610.0 and failure["steady_ended"] is None
    assert failure["observed_steady_seconds"] == 3.0 and failure["lease_heartbeats"] == 1
    assert not failure["completed_steady_window"] and not failure["slo_pass"]
