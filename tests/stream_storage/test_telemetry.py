"""Small runnable guard for the profiler's easily inflated SQL metric."""

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
    import pytest

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
