"""Both Worker maintenance entrances share one rate ceiling and owned drain."""

from types import SimpleNamespace

from zebra_agent_worker.worker_loop_service import WorkerLoopService

from tests.agent_storage.test_postgres_migrations import (
    isolated_migration_dsn as _maintenance_dsn_fixture,
)
from tests.agent_storage.test_postgres_migrations import (
    postgres_dsn as _maintenance_postgres_fixture,
)

isolated_migration_dsn = _maintenance_dsn_fixture

postgres_dsn = _maintenance_postgres_fixture


def test_both_entrances_rate_limit_recovery_and_owned_drain(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("zebra_agent_worker.worker_loop_service.time.monotonic", lambda: now[0])
    calls = []
    relay = SimpleNamespace(tick=lambda: calls.append("relay"), close=lambda: calls.append("close"))
    service = WorkerLoopService(
        SimpleNamespace(list_ready_sessions=lambda **k: []),
        SimpleNamespace(),
        stream_hint_relay=relay,
        client_effect_recovery=lambda: calls.append("recovery"),
    )
    service.maintenance_once(worker_id="w", batch_size=1, lease_ttl_seconds=30)
    service.poll_once(worker_id="w")
    assert calls.count("relay") == 1 and "recovery" in calls
    now[0] += 1
    service.poll_once(worker_id="w")
    service.maintenance_once(worker_id="w", batch_size=1, lease_ttl_seconds=30)
    assert calls.count("relay") == 2
    service.drain()
    assert calls[-1] == "close"


def test_supplement_both_entrances_inclusive_empty_maintenance_cost(
    isolated_migration_dsn, record_property
):
    import json
    import os
    from time import sleep

    import psycopg
    from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
    from agent_integrations.redis_live_fanout import RedisLiveEventFanout
    from agent_runtime.stream_hint_relay import StreamHintRelay
    from agent_storage.postgres.migration_runner import apply_postgres_migrations
    from zebra_agent_worker.ag_ui_projection_work import AgUiProjectionWorkService

    from tests.agent_integrations.test_checkpoint_notification_retry import _full_pg_stores
    from tests.stream_storage.telemetry import Telemetry, phase

    dsn = isolated_migration_dsn
    apply_postgres_migrations(dsn)
    stores = _full_pg_stores(dsn)
    fanout = RedisLiveEventFanout.from_url(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"])
    relay = StreamHintRelay(dsn, "local", fanout)
    consumers = [
        AgUiCheckpointConsumer(
            stores.tasks,
            queue,
            namespace="local",
            checkpoint_committed=fanout.publish_checkpoint,
            notification_required=True,
        )
        for queue in (stores.projection_work, stores.coverage_projection_work)
    ]
    background = AgUiProjectionWorkService(consumers[0], coverage_consumer=consumers[1])
    service = WorkerLoopService(
        stores.sessions, SimpleNamespace(), stream_hint_relay=relay, projection_work=background
    )
    ticks, original = [], relay.tick

    def actual_tick():
        ticks.append(1)
        return original()

    relay.tick = actual_tick
    telemetry = Telemetry()
    telemetry.stage = "whole-maintenance"
    with telemetry.installed():
        with psycopg.connect(dsn) as connection:
            before = connection.execute("SELECT pg_current_wal_insert_lsn()").fetchone()[0]
        try:
            with phase("maintenance_once"):
                service.maintenance_once(worker_id="relay-cost", batch_size=1, lease_ttl_seconds=30)
            sleep(1.05)
            with phase("poll_once"):
                service.poll_once(worker_id="relay-cost")
                service.maintenance_once(worker_id="relay-cost", batch_size=1, lease_ttl_seconds=30)
                service.poll_once(worker_id="relay-cost")
            sleep(0.15)
            assert len(ticks) == 2
        finally:
            service.drain()
        with psycopg.connect(dsn) as connection:
            wal = connection.execute(
                "SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),%s)", (before,)
            ).fetchone()[0]
    report = telemetry.report()
    sql = sum(n for key, n in report["calls"].items() if "/sql:" in key)
    sockets = sum(n for key, n in report["calls"].items() if key.endswith("/new_pg_socket"))
    assert sql > 10 and sockets > 2  # Includes actual bootstrap and both ordinary/coverage polls.
    assert any(
        "/setup/sql:" in key for key in report["calls"]
    )  # Background threads are not filtered.
    record_property("whole_maintenance_telemetry", json.dumps(report, sort_keys=True))
    record_property("whole_maintenance_sql", sql)
    record_property("whole_maintenance_sockets", sockets)
    record_property("whole_maintenance_wal_bytes", int(wal))
    record_property("relay_actual_ticks", len(ticks))
    record_property(
        "configured_background",
        "ordinary+coverage projection bootstrap/poll; relay; ready-session scan",
    )
    record_property("not_configured", "memory/child/client-effect recovery; GC not implemented")
    assert background._thread is not None and not background._thread.is_alive()
