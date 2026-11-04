"""Explicit capacity scopes: no model, business effects or production database."""

import json

import psycopg
import pytest

from tests.agent_storage.test_postgres_command_wakeup import dsn as _schema_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture


def profile_data():
    return {"pool": 2, "normal": 2, "read": 1, "control": 2, "probe": 1,
            "max_connections": 64, "server_reserved": 3, "external": 4,
            "execution_slots": 2,
            "fleet": {"api": 1, "worker": 1, "executor": 2,
                      "cleanup": 1, "scheduler": 1}}


def test_capacity_reserves_read_control_and_never_releases_borrow_early():
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        ConnectionBudget,
        DatabaseCapacityExceeded,
    )

    profile = CapacityProfile.parse(json.dumps(profile_data()))
    budget = ConnectionBudget("dbname=one", profile, "api")
    first, second = budget.acquire("normal"), budget.acquire("normal")
    with pytest.raises(DatabaseCapacityExceeded):
        budget.acquire("normal")
    reader, stopper = budget.acquire("read"), budget.acquire("control")
    assert budget.stats()["active"] == {"normal": 2, "read": 1, "control": 1, "probe": 0}
    first.release()
    first.release()  # Real close may be called repeatedly; do not manufacture capacity.
    third = budget.acquire("normal")
    with pytest.raises(DatabaseCapacityExceeded):
        budget.acquire("normal")
    for permit in (second, reader, stopper, third):
        permit.release()
    assert sum(budget.stats()["active"].values()) == 0


def test_fleet_budget_counts_executor_and_rollout_peaks():
    from agent_storage.postgres.capacity_profile import CapacityProfile

    data = profile_data()
    value = CapacityProfile.parse(json.dumps(data))
    assert value.fleet_connections == 6 * 8
    data["fleet"]["executor"] = 1
    with pytest.raises(ValueError):
        CapacityProfile.parse(json.dumps(data))
    data = profile_data()
    data["max_connections"] = 48
    with pytest.raises(ValueError):
        CapacityProfile.parse(json.dumps(data))


def test_executor_limits_are_charged_and_enforced_separately():
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        ConnectionBudget,
        DatabaseCapacityExceeded,
    )

    data = profile_data()
    data["executor_limits"] = dict(pool=1, normal=1, read=1, control=1, probe=1)
    data["max_connections"] = 49
    profile = CapacityProfile.parse(json.dumps(data))
    assert profile.fleet_connections == 42
    assert profile.limit("executor", "pool") == 1
    assert profile.limit("api", "pool") == 2
    budget = ConnectionBudget("dbname=one", profile, "executor")
    permit = budget.acquire("normal")
    try:
        with pytest.raises(DatabaseCapacityExceeded):
            budget.acquire("normal")
    finally:
        permit.release()
    data["max_connections"] = 48
    with pytest.raises(ValueError, match="exceeds server"):
        CapacityProfile.parse(json.dumps(data))


def test_api_read_slots_are_charged_only_to_api_peak():
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import ConnectionBudget

    data = profile_data()
    base = CapacityProfile.parse(json.dumps(data))
    data["api_read"] = base.read + 2
    data["max_connections"] = (
        base.fleet_connections + base.server_reserved + base.external + 2 * base.fleet["api"]
    )
    profile = CapacityProfile.parse(json.dumps(data))
    assert profile.limit("worker", "read") == base.read
    assert profile.limit("executor", "read") == base.read
    budget = ConnectionBudget("dbname=one", profile, "api")
    permits = [budget.acquire("read") for _ in range(data["api_read"])]
    for permit in permits:
        permit.release()
    data["max_connections"] -= 1
    with pytest.raises(ValueError, match="exceeds server"):
        CapacityProfile.parse(json.dumps(data))


@pytest.mark.parametrize("field,value", [("pool", True), ("normal", 0),
                                         ("read", -1), ("control", 1000000)])
def test_profile_rejects_unsafe_capacity(field, value):
    from agent_storage.postgres.capacity_profile import CapacityProfile

    data = profile_data()
    data[field] = value
    with pytest.raises(ValueError):
        CapacityProfile.parse(json.dumps(data))


# Existing isolated-schema fixtures: never point these at a business database.

dsn = _schema_fixture
postgres_dsn = _pg_fixture


@pytest.fixture
def budget_dsn(dsn):
    from uuid import uuid4

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    role = "capacity_" + uuid4().hex
    with psycopg.connect(dsn) as admin:
        schema = admin.execute("SELECT current_schema()").fetchone()[0]
        row = admin.execute("SHOW max_connections").fetchone()
        value = profile_data()
        value["max_connections"] = int(row[0])
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER").format(
            sql.Identifier(role), sql.Literal("isolated-capacity-test")))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT ALL ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(role)))
    try:
        yield make_conninfo(dsn, user=role, password="isolated-capacity-test"), value
    finally:
        with psycopg.connect(dsn) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_real_saturation_leaves_native_force_stop_and_original_get_available(
    dsn, budget_dsn, monkeypatch,
):
    from collections import Counter
    from contextlib import ExitStack
    from threading import Lock
    from time import monotonic, process_time
    from uuid import UUID

    from agent_storage.postgres.connection_capacity import PROFILE_ENV, DatabaseCapacityExceeded
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.database import PostgresDatabase
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from zebra_agent_api import RouteAdapter
    from zebra_agent_api.database_budget import (
        ApiDatabaseCalls,
        DatabaseBudgetMiddleware,
        database_call,
    )

    from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
    from tests.agent_storage.test_postgres_force_stops import _app, _force, _progress, _setup

    lease = _setup(dsn)
    role_dsn, value = budget_dsn
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    with postgres_pool_scope(role_dsn, component="api") as budget:
        database = PostgresDatabase(role_dsn, deployment_namespace=NAMESPACE)
        adapter = RouteAdapter(_app(role_dsn))
        app = FastAPI()
        app.add_middleware(DatabaseBudgetMiddleware, budget=budget)
        calls = ApiDatabaseCalls(budget)
        app.state.database_calls = calls

        @app.post("/tasks/{sid}/cancel")
        async def cancel(sid):
            result = await database_call(app, adapter.handle, _force(UUID(sid)))
            return JSONResponse(result.body, status_code=result.status_code)

        @app.get("/tasks/{sid}/stop")
        async def progress(sid):
            result = await database_call(app, adapter.handle, _progress(UUID(sid)))
            return JSONResponse(result.body, status_code=result.status_code)

        with ExitStack() as held, TestClient(app) as client:
            for _ in range(value["normal"]):
                held.enter_context(database.connect_task_io())
            for _ in range(value["pool"]):
                held.enter_context(database._pool.connection())
            with pytest.raises(DatabaseCapacityExceeded):
                database.connect_task_io()
            from agent_storage.postgres.connection_capacity import current_lane
            execute = psycopg.Connection.execute
            queries, query_lock = Counter(), Lock()

            def counted(connection, *args, **kwargs):
                with query_lock:
                    queries[current_lane()] += 1
                return execute(connection, *args, **kwargs)

            monkeypatch.setattr(psycopg.Connection, "execute", counted)
            cpu, started = process_time(), monotonic()
            first = client.post(f"/tasks/{lease.session_id}/cancel")
            control_ms = (monotonic() - started) * 1000
            assert first.status_code == 202, first.text
            assert first.json()["request_accepted"] and not first.json()["resources_released"]
            reads = []
            for _ in range(20):
                started = monotonic()
                assert client.get(f"/tasks/{lease.session_id}/stop").json() == first.json()
                reads.append((monotonic() - started) * 1000)
            assert queries["control"] > 0 and queries["read"] > 0
            import os
            from pathlib import Path
            if evidence := os.environ.get("ZEBRA_CAPACITY_EVIDENCE_PATH"):
                Path(evidence).write_text(json.dumps({
                    "kind": "micro_only_not_E1", "control_requests": 1,
                    "original_get_requests": 20, "control_ms": control_ms,
                    "read_p50_ms": sorted(reads)[9], "read_p95_ms": sorted(reads)[18],
                    "read_max_ms": max(reads), "parent_process_cpu_seconds": process_time()-cpu,
                    "sql_calls_by_lane": dict(queries), "capacity": budget.stats(),
                    "normal_and_pool_fully_held": True, "run_replayed": False,
                }, indent=2))
            assert budget.stats()["active"]["normal"] == value["normal"]
            assert budget.stats()["rejected"]["normal"] == 1
        calls.close()
        assert sum(budget.stats()["active"].values()) == 0


def test_real_closed_sockets_return_permits_once_and_failed_open_returns_them(
    budget_dsn, monkeypatch,
):

    from agent_storage.postgres.connection_capacity import PROFILE_ENV
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.task_io import TaskIoConnections

    role_dsn, value = budget_dsn
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    with postgres_pool_scope(role_dsn, component="api") as budget:
        connector = TaskIoConnections(role_dsn)
        connection = connector.connect()
        assert budget.stats()["active"]["normal"] == 1
        connection.close()
        connection.close()
        assert budget.stats()["active"]["normal"] == 0
        # Only the connection attempt address changes; the configured DSN stays bound.
        monkeypatch.setattr(connector, "_resolve", lambda deadline:
                            ({**connector._params, "port": "1", "hostaddr": "127.0.0.1"},))
        with pytest.raises((psycopg.OperationalError, TimeoutError)):
            connector.connect(timeout_seconds=0.25)
        assert budget.stats()["active"]["normal"] == 0


def test_real_callback_retains_socket_quota_until_scope_exit(budget_dsn, monkeypatch):
    from time import monotonic

    from agent_storage.postgres.connection_capacity import PROFILE_ENV
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.connection_scope import postgres_connection_scope
    from agent_storage.postgres.task_io import TaskIoConnections, task_io_deadline

    role_dsn, value = budget_dsn
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    with postgres_pool_scope(role_dsn, component="worker") as budget:
        connector = TaskIoConnections(role_dsn)
        with postgres_connection_scope(task_io=True), task_io_deadline(monotonic() + 2):
            with connector.connect() as connection:
                pid = connection.info.backend_pid
            assert budget.stats()["active"]["normal"] == 1
            with connector.connect() as connection:
                assert connection.info.backend_pid == pid
                assert budget.stats()["active"]["normal"] == 1
        assert budget.stats()["active"]["normal"] == 0


def _hold_worker_capacity(dsn, value, ready, finish):
    import os
    from contextlib import ExitStack

    from agent_storage.postgres.connection_capacity import PROFILE_ENV
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.database import PostgresDatabase

    os.environ[PROFILE_ENV] = json.dumps(value)
    with postgres_pool_scope(dsn, component="worker",
                             execution_slots=value["execution_slots"]) as budget:
        database = PostgresDatabase(dsn, deployment_namespace="test")
        with ExitStack() as held:
            for _ in range(value["normal"]):
                held.enter_context(database.connect_task_io())
            for _ in range(value["pool"]):
                held.enter_context(database._pool.connection())
            ready.put(budget.stats())
            assert finish.wait(15)
        ready.put(budget.stats())


def test_real_two_process_budgets_reserve_read_and_control(budget_dsn, monkeypatch):
    import multiprocessing
    from contextlib import ExitStack
    from time import monotonic

    from agent_storage.postgres.connection_capacity import PROFILE_ENV, capacity_lane
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.database import PostgresDatabase

    role_dsn, value = budget_dsn
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    context = multiprocessing.get_context("spawn")
    ready, finish = context.Queue(), context.Event()
    worker = context.Process(target=_hold_worker_capacity, args=(role_dsn, value, ready, finish))
    worker.start()
    try:
        assert ready.get(timeout=10)["active"]["normal"] == value["normal"]
        with postgres_pool_scope(role_dsn, component="api") as budget, ExitStack() as held:
            database = PostgresDatabase(role_dsn, deployment_namespace="test")
            for _ in range(value["normal"]):
                held.enter_context(database.connect_task_io())
            for _ in range(value["pool"]):
                held.enter_context(database._pool.connection())
            started = monotonic()
            for lane in ("control", "read"):
                with capacity_lane(lane), database.connect_task_io() as connection:
                    assert connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
            assert monotonic() - started < 1
            assert budget.stats()["active"]["normal"] == value["normal"]
        finish.set()
        assert sum(ready.get(timeout=5)["active"].values()) == 0
        worker.join(5)
        assert worker.exitcode == 0
    finally:
        finish.set()
        worker.join(5)
        if worker.is_alive():
            worker.kill()
            worker.join(5)
        ready.close()


def test_thread_resources_propagate_without_business_authority():
    import asyncio
    from contextvars import ContextVar

    from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        ConnectionBudget,
        capacity_for,
        capacity_scope,
        current_lane,
    )

    authority = ContextVar("test_business_authority", default=None)
    authority_token = authority.set("must-not-leak")
    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "worker"
    )

    async def quarantine(*args):
        pass

    async def exercise():
        consumer = CommandWakeupConsumer(
            "dbname=one", deployment_namespace="test", owner="worker",
            execute_claimed=lambda lease: None, quarantine=quarantine,
        )
        try:
            def observe():
                return capacity_for("dbname=one"), current_lane(), authority.get()
            result = await consumer._db(consumer._control, observe)
            assert result == (budget, "control", None)
        finally:
            await consumer.close()

    try:
        with capacity_scope(budget):
            asyncio.run(exercise())
    finally:
        authority.reset(authority_token)


def test_enabled_profile_rejects_unscoped_and_foreign_open(monkeypatch):
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        PROFILE_ENV,
        ConnectionBudget,
        capacity_scope,
    )
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_io import TaskIoConnections

    monkeypatch.setenv(PROFILE_ENV, json.dumps(profile_data()))
    with pytest.raises(RuntimeError, match="no process composition"):
        TaskIoConnections("dbname=one").connect()
    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "api"
    )
    with capacity_scope(budget):
        dormant = PostgresDatabase("dbname=two", deployment_namespace="test")
        with pytest.raises(ValueError, match="outside the composed budget"):
            dormant.connect()


def test_real_failed_close_keeps_permit_until_native_closed(budget_dsn, monkeypatch):
    from agent_storage.postgres.connection_capacity import PROFILE_ENV
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.task_io import TaskIoConnections

    role_dsn, value = budget_dsn
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    with postgres_pool_scope(role_dsn, component="api") as budget:
        connection = TaskIoConnections(role_dsn).connect()
        original = psycopg.Connection.close

        def failure(self):
            raise RuntimeError("injected native close failure")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(psycopg.Connection, "close", failure)
                with pytest.raises(RuntimeError):
                    connection.close()
                assert budget.stats()["active"]["normal"] == 1
        finally:
            assert psycopg.Connection.close is original
            connection.close()
        assert budget.stats()["active"]["normal"] == 0


def test_real_health_probe_has_budget_when_all_business_lanes_are_full(
    dsn, budget_dsn, monkeypatch,
):
    from contextlib import ExitStack
    from dataclasses import replace
    from types import SimpleNamespace

    from agent_storage.postgres.connection_capacity import PROFILE_ENV, capacity_lane
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.database import PostgresDatabase
    from zebra_agent_api.health_readiness import ApiHealth

    from tests.agent_storage.test_postgres_force_stops import NAMESPACE, _app, _setup

    _setup(dsn)
    role_dsn, value = budget_dsn
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    with postgres_pool_scope(role_dsn, component="api") as budget, ExitStack() as held:
        native = _app(role_dsn)
        api = SimpleNamespace(settings=replace(native.settings, database_url=role_dsn),
                              stores=native.stores)
        health = ApiHealth(api)
        database = PostgresDatabase(role_dsn, deployment_namespace=NAMESPACE)
        for lane in ("normal", "read", "control"):
            with capacity_lane(lane):
                for _ in range(value[lane]):
                    held.enter_context(database.connect_task_io())
        for _ in range(value["pool"]):
            held.enter_context(database._pool.connection())
        health.sample_once()
        assert health.status() == "ready"
        assert budget.stats()["peak"]["probe"] == 1
        assert budget.stats()["active"]["probe"] == 0


def test_real_private_child_factory_is_inside_its_budget_scope(
    budget_dsn, monkeypatch, capsys,
):
    from types import SimpleNamespace

    import agent_storage
    import zebra_agent_config
    from agent_storage.postgres.connection_capacity import PROFILE_ENV, capacity_for
    from agent_storage.postgres.task_io import TaskIoConnections
    from zebra_agent_worker import loop, session_process
    from zebra_agent_worker import session_process_child as child

    role_dsn, value = budget_dsn
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    monkeypatch.setenv("ZEBRA_SESSION_PROCESS_FACTORY", "tests.capacity_operator:build")
    monkeypatch.setattr(child.sys, "argv", ["child", "--check"])
    settings = SimpleNamespace(deployment="cloud", storage_authority="postgresql",
                               database_url=role_dsn)
    monkeypatch.setattr(zebra_agent_config, "load_settings", lambda: settings)
    monkeypatch.setattr(session_process, "settings_digest", lambda settings: "test-digest")
    monkeypatch.setattr(agent_storage, "cloud_composition_from_environment", lambda: object())
    sentinel = object()
    imported = child.importlib.import_module

    def factory(settings, cloud):
        assert capacity_for(role_dsn) is not None
        with TaskIoConnections(role_dsn).connect() as connection:
            assert connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
        return sentinel

    monkeypatch.setattr(child.importlib, "import_module", lambda name:
                        SimpleNamespace(build=factory) if name == "tests.capacity_operator"
                        else imported(name))

    def compose(**kwargs):
        assert kwargs["cloud_worker_composition"] is sentinel
        return SimpleNamespace(_execution_service=object())

    monkeypatch.setattr(loop, "build_worker_loop_service", compose)
    child.main()
    result = json.loads(capsys.readouterr().out)
    assert result["cloud_composition_ready"] and result["run_executed"] is False


def test_nested_root_cannot_multiply_process_budget(monkeypatch):
    from agent_storage.postgres import connection_pool
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        PROFILE_ENV,
        ConnectionBudget,
        capacity_scope,
    )

    value = profile_data()
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    budget = ConnectionBudget("dbname=one", CapacityProfile.parse(json.dumps(value)), "api")

    def must_not_open(*args, **kwargs):
        pytest.fail("nested process root attempted another bootstrap connection")

    monkeypatch.setattr(connection_pool, "connect", must_not_open)
    with capacity_scope(budget), pytest.raises(ValueError, match="already composed"):
        with connection_pool.postgres_pool_scope("dbname=one", component="worker"):
            pytest.fail("nested process budget admitted")


def test_real_executor_limits_cap_pool_and_direct_sockets(budget_dsn, monkeypatch):
    from contextlib import ExitStack

    from agent_storage.postgres.connection_capacity import (
        PROFILE_ENV,
        DatabaseCapacityExceeded,
        connect,
    )
    from agent_storage.postgres.connection_pool import composition_pool, postgres_pool_scope
    from psycopg_pool import PoolTimeout

    dsn, value = budget_dsn
    value["executor_limits"] = dict(pool=1, normal=2, read=1, control=1, probe=1)
    monkeypatch.setenv(PROFILE_ENV, json.dumps(value))
    with postgres_pool_scope(dsn, component="executor") as budget, ExitStack() as sockets:
        pool = composition_pool(dsn)
        assert pool is not None and budget is not None
        pooled = sockets.enter_context(pool.connection())
        normal = [sockets.enter_context(connect(dsn, lane="normal")) for _ in range(2)]
        control = sockets.enter_context(connect(dsn, lane="control"))
        assert len({connection.info.backend_pid for connection in [pooled, *normal, control]}) == 4
        assert control.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(PoolTimeout), pool.connection(timeout=0.05):
            pytest.fail("executor pool exceeded its limit")
        with pytest.raises(DatabaseCapacityExceeded), connect(dsn, lane="normal"):
            pytest.fail("executor normal lane exceeded its limit")
        assert budget.stats()["peak"]["normal"] == 2
