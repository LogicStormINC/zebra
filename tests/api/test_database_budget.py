"""HTTP bulkheads are resource policy; route authorization remains authoritative."""

import json

import pytest
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
    from agent_storage.postgres.async_dispatch import async_dispatch_scope, storage_call
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import (
        ConnectionBudget,
        capacity_lane,
    )
    from zebra_agent_api.database_budget import ApiDatabaseCalls, ApiDatabaseExecutorSaturated

    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "api"
    )
    calls, finish = ApiDatabaseCalls(budget), Event()
    entered = [Event() for _ in range(budget.profile.pool + budget.profile.normal)]

    def blocked(index):
        entered[index].set()
        assert finish.wait(5)

    async def exercise():
        with capacity_lane("read"), async_dispatch_scope(calls.call):
            assert await calls.call(lambda: asyncio.run(storage_call(lambda: "nested"))) == "nested"
        normal = [asyncio.create_task(calls.call(blocked, index)) for index in range(len(entered))]
        try:
            assert all(await asyncio.gather(*(asyncio.to_thread(e.wait, 1) for e in entered)))
            for task in normal:
                task.cancel()
            await asyncio.gather(*normal, return_exceptions=True)
            with pytest.raises(ApiDatabaseExecutorSaturated):
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


@pytest.mark.parametrize("callback", ["preflight", "storage"])
def test_cancelled_cloud_preflight_keeps_read_thread_slot(callback, monkeypatch):
    import asyncio
    from threading import Event
    from types import SimpleNamespace

    import httpx
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import ConnectionBudget, capacity_scope
    from fastapi.responses import JSONResponse
    from zebra_agent_api.ag_ui_task_view import authorized_task_preflight
    from zebra_agent_api.database_budget import configure_database_budget
    from zebra_agent_api.responses import ApiResponse

    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "api"
    )
    app, started, finish = FastAPI(), Event(), Event()
    with capacity_scope(budget):
        configure_database_budget(app, SimpleNamespace(), "dbname=one")
    live = []

    def blocking_read():
        live.append(True)
        started.set()
        assert finish.wait(5)
        return ApiResponse(200, {"status": "ok"})

    @app.get("/tasks/one/stop")
    async def cloud_read():
        if callback == "storage":
            from agent_storage.postgres.extensions import PostgresExtensionStore

            store = PostgresExtensionStore("dbname=one", deployment_namespace="test")
            monkeypatch.setattr(store, "_authorize_frozen_skills", lambda *_: blocking_read())
            result = await store.authorize_frozen_skills(scope=None, installations=())
        else:
            result = await authorized_task_preflight(
                lambda: None, blocking_read, authorization_expires_at=None,
            )
        return JSONResponse(result.body, status_code=result.status_code)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://test") as client:
            first = asyncio.create_task(client.get("/tasks/one/stop"))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)
                try:
                    second = await asyncio.wait_for(client.get("/tasks/one/stop"), 0.5)
                except TimeoutError:
                    second = None
                assert len(live) == 1, "cancelled cloud read escaped the configured read pool"
                assert second is not None and second.status_code == 503
            finally:
                finish.set()
                await asyncio.gather(first, return_exceptions=True)
    try:
        asyncio.run(exercise())
    finally:
        finish.set()
        app.state.database_calls.close()


def test_cloud_legacy_health_does_not_dispatch_synchronous_preflight(tmp_path, monkeypatch):
    from zebra_agent_api import http as module

    from tests.api.test_host_auth_http import _cloud_client

    async def must_not_dispatch(*args, **kwargs):
        raise AssertionError("cached health entered the synchronous read dispatcher")

    monkeypatch.setattr(module, "authorized_task_preflight", must_not_dispatch)
    client = _cloud_client(tmp_path, None)
    assert client.get("/health").json()["status"] == "ok"


@pytest.mark.parametrize("read_limit", [1, 2])
def test_extension_list_metadata_fanout_fits_read_budget(read_limit, monkeypatch):
    from time import sleep
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agent_core.ports.extensions import ExtensionStore, SkillInstallationPage
    from agent_core.ports.skill_publications import SkillPublicationNotFoundError
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import ConnectionBudget, capacity_scope
    from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
    from agent_tools.skill_publications import SkillPublicationService
    from fastapi import Request
    from zebra_agent_api.database_budget import configure_database_budget
    from zebra_agent_api.extension_reads import extension_read_response

    from tests.api.test_extension_reads import SKILL, VERIFIED

    profile = profile_data() | {"read": read_limit}
    budget = ConnectionBudget("dbname=one", CapacityProfile.parse(json.dumps(profile)), "api")
    app, store = FastAPI(), AsyncMock(spec=ExtensionStore)
    store.list_skills.return_value = SkillInstallationPage(items=tuple(
        SKILL.model_copy(update={"installation_id": f"installed-{i}"}) for i in range(3)
    ))
    publications = PostgresSkillPublicationStore("dbname=one", deployment_namespace="test")
    completed = []

    def missing_metadata(*_):
        sleep(0.05)
        completed.append(True)
        raise SkillPublicationNotFoundError("legacy record has no publication metadata")

    monkeypatch.setattr(publications, "_get", missing_metadata)
    with capacity_scope(budget):
        configure_database_budget(app, SimpleNamespace(), "dbname=one")

    @app.get("/v1/extensions/skill-installations")
    async def listing(request: Request):
        request.state.verified_host_grant = VERIFIED
        return await extension_read_response(
            request, store=store, deployment="cloud",
            publications=SkillPublicationService(publications, None, "test"),
        )

    try:
        with TestClient(app) as client:
            response = client.get("/v1/extensions/skill-installations")
        assert response.status_code == 200
        assert len(response.json()["items"]) == len(completed) == 3
    finally:
        app.state.database_calls.close()


def test_host_read_waits_before_dispatch_and_cancellation_never_invokes_it():
    import asyncio
    from threading import Event

    import pytest
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import ConnectionBudget, capacity_lane
    from fastapi import FastAPI
    from zebra_agent_api.ag_ui_task_view import authorized_task_preflight
    from zebra_agent_api.database_budget import ApiDatabaseCalls

    profile = CapacityProfile.parse(json.dumps({**profile_data(), "read": 1}))
    calls = ApiDatabaseCalls(ConnectionBudget("dbname=one", profile, "api"))
    app = FastAPI()
    app.state.database_calls = calls
    entered, release = Event(), Event()
    invoked = []

    def occupy():
        entered.set()
        assert release.wait(3)

    async def exercise():
        with capacity_lane("read"):
            busy = asyncio.create_task(calls.call(occupy))
            assert await asyncio.to_thread(entered.wait, 1)
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.03):
                    await calls.call(lambda: invoked.append("cancelled"), wait_for_read_slot=True)
            waiting = asyncio.create_task(
                authorized_task_preflight(
                    lambda: None,
                    lambda: invoked.append("admitted"),
                    authorization_expires_at=None,
                    http_app=app,
                )
            )
            await asyncio.sleep(0.02)
            assert not invoked
            release.set()
            await asyncio.gather(busy, waiting)
            assert invoked == ["admitted"]

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        calls.close()


def test_original_receipt_has_capacity_when_stream_reads_are_saturated():
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import ConnectionBudget, current_lane
    from zebra_agent_api.database_budget import DatabaseBudgetMiddleware

    profile = CapacityProfile.parse(json.dumps(profile_data() | {"receipt": 1}))
    baseline = CapacityProfile.parse(json.dumps(profile_data()))
    assert profile.fleet_connections == baseline.fleet_connections + profile.fleet["api"]
    budget = ConnectionBudget("dbname=one", profile, "api")
    app = FastAPI()
    app.add_middleware(DatabaseBudgetMiddleware, budget=budget)

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    def request(path):
        budget.acquire(current_lane()).release()
        return {"lane": current_lane()}

    receipt = "/v1/admission-operations/00000000-0000-0000-0000-000000000001"
    read = budget.acquire("read")
    try:
        with TestClient(app) as client:
            assert client.get("/tasks/example/stream").status_code == 503
            assert client.get(receipt).json() == {"lane": "receipt"}
            assert client.get(receipt + "/observation").status_code == 503
            assert client.post(receipt).json() == {"lane": "normal"}
            assert client.post("/tasks/example/stop").json() == {"lane": "control"}
    finally:
        read.release()


def test_cursor_resume_waits_within_read_budget_without_queueing_other_reads():
    import asyncio

    import httpx
    from agent_storage.postgres.capacity_profile import CapacityProfile
    from agent_storage.postgres.connection_capacity import ConnectionBudget
    from zebra_agent_api.database_budget import DatabaseBudgetMiddleware

    profile = CapacityProfile.parse(json.dumps(profile_data() | {"read": 2, "api_read": 1}))
    budget = ConnectionBudget("dbname=one", profile, "api")
    app = FastAPI()
    app.add_middleware(DatabaseBudgetMiddleware, budget=budget)

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        @app.get("/tasks/{task_id}/stream")
        async def stream(task_id: str):
            if task_id == "holding":
                entered.set()
                await release.wait()
            return {"task": task_id}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            holding = asyncio.create_task(client.get("/tasks/holding/stream"))
            await entered.wait()
            resumed = asyncio.create_task(client.get("/tasks/resume/stream?after_sequence=2"))
            try:
                await asyncio.sleep(0)
                assert not resumed.done()
                overflow = await client.get("/tasks/overflow/stream?after_sequence=2")
                assert overflow.status_code == 503
                ordinary = await client.get("/tasks/ordinary/stream")
                assert ordinary.status_code == 503
            finally:
                release.set()
                await holding
            assert (await resumed).json() == {"task": "resume"}

    asyncio.run(exercise())
