"""HTTP bulkheads are resource policy; route authorization remains authoritative."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.agent_storage.test_postgres_connection_capacity import profile_data


def test_execution_saturation_keeps_control_and_read_routes_available():
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        ConnectionBudget,
        capacity_for,
        current_lane,
    )
    from zebra_agent_api.database_budget import DatabaseBudgetMiddleware

    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "api"
    )
    normal = [budget.acquire("normal") for _ in range(2)]
    app = FastAPI()
    app.add_middleware(DatabaseBudgetMiddleware, budget=budget)
    calls = []

    @app.api_route("/tasks/{task_id}/{action}", methods=["POST", "GET"])
    def request(task_id, action):
        calls.append((task_id, action))
        permit = capacity_for("dbname=one").acquire(current_lane())
        permit.release()
        return {"lane": current_lane()}

    with TestClient(app) as client:
        assert client.post("/tasks/one/run").status_code == 503
        assert client.post("/tasks/one/cancel").json() == {"lane": "control"}
        assert client.get("/tasks/one/stop").json() == {"lane": "read"}
        assert calls == [("one", "run"), ("one", "cancel"), ("one", "stop")]
    for permit in normal:
        permit.release()


def test_cancelled_normal_calls_keep_slots_and_do_not_starve_control():
    import asyncio
    from threading import Event

    import pytest
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        ConnectionBudget,
        DatabaseCapacityExceeded,
        capacity_lane,
    )
    from zebra_agent_api.database_budget import ApiDatabaseCalls

    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "api"
    )
    calls, finish = ApiDatabaseCalls(budget), Event()
    entered = [Event() for _ in range(budget.profile.pool + budget.profile.normal)]

    def blocked(index):
        entered[index].set()
        assert finish.wait(5)

    async def exercise():
        normal = [asyncio.create_task(calls.call(blocked, index)) for index in range(len(entered))]
        try:
            assert all(await asyncio.gather(*(asyncio.to_thread(e.wait, 1) for e in entered)))
            for task in normal:
                task.cancel()
            await asyncio.gather(*normal, return_exceptions=True)
            with pytest.raises(DatabaseCapacityExceeded):
                await calls.call(lambda: None)
            with capacity_lane("control"):
                assert await calls.call(lambda: "control") == "control"
            with capacity_lane("read"):
                assert await calls.call(lambda: "read") == "read"
        finally:
            finish.set()
            await asyncio.gather(*normal, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        finish.set()
        calls.close()


def test_real_cached_health_bypasses_full_dispatchers(tmp_path):
    import asyncio
    from threading import Event

    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import ConnectionBudget, capacity_lane
    from zebra_agent_api.database_budget import ApiDatabaseCalls, DatabaseBudgetMiddleware
    from zebra_agent_api.http import create_http_app
    from zebra_agent_config import load_settings

    settings = load_settings(env={"ZEBRA_DATABASE_URL": str(tmp_path / "health.sqlite")})
    app = create_http_app(database_path=tmp_path / "health.sqlite", settings=settings)
    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "api"
    )
    calls, finish, started = ApiDatabaseCalls(budget), Event(), []
    app.state.database_calls = calls
    app.add_middleware(DatabaseBudgetMiddleware, budget=budget)

    def blocked(event):
        event.set()
        assert finish.wait(5)

    async def exercise():
        tasks = []
        try:
            for lane, count in (("normal", 4), ("read", 1)):
                with capacity_lane(lane):
                    for _ in range(count):
                        event = Event()
                        started.append(event)
                        tasks.append(asyncio.create_task(calls.call(blocked, event)))
            assert all(await asyncio.gather(*(asyncio.to_thread(e.wait, 1) for e in started)))
            with TestClient(app) as client:
                assert client.get("/health").status_code == 200
                assert client.get("/health/live").status_code == 200
        finally:
            finish.set()
            await asyncio.gather(*tasks)

    try:
        asyncio.run(exercise())
    finally:
        finish.set()
        calls.close()
