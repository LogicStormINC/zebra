"""No network or containers: actual HTTP dispatch and bounded health observations."""

from threading import Event
from time import monotonic

from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.health_readiness import ApiHealth

from tests.api.test_host_auth_http import _cloud_client, _local_settings


def test_legacy_health_and_exact_anonymous_get_paths(tmp_path):
    client = _cloud_client(tmp_path, None)
    for path in ("/health/live", "/health/ready"):
        response = client.get(path)
        assert response.status_code in (200, 503)
        assert set(response.json()) == {"status"}
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").status_code == 503  # Lifespan has not started.
    assert client.get("/health").json()["status"] == "ok"
    for method, path in [
        ("POST", "/health/ready"),
        ("GET", "/health/ready/private"),
        ("GET", "/health/live/"),
        ("GET", "/sessions/not-a-uuid"),
    ]:
        assert client.request(method, path).status_code in (401, 403)


def test_local_http_lifespan_and_shutdown_do_not_change_legacy_auth(tmp_path):
    app = create_http_app(tmp_path / "local.sqlite", settings=_local_settings(auth_token="secret"))
    health = app.state.health
    with TestClient(app) as client:
        assert health.sampled.wait(1)
        assert client.get("/health/ready").json() == {"status": "ready"}
        assert client.get("/sessions/nope").status_code == 401
        assert client.get("/health").json()["status"] == "ok"
    assert health.status() == "not_ready"
    assert not health.running


def test_stale_failed_recovered_and_closed_observations():
    now = [10.0]
    available = [True]
    health = ApiHealth(check=lambda: available[0], clock=lambda: now[0])
    assert health.status() == "not_ready"
    health.sample_once()
    assert health.status() == "ready"
    now[0] += 6
    assert health.status() == "not_ready"
    available[0] = False
    health.sample_once()
    assert health.status() == "not_ready"
    available[0] = True
    health.sample_once()
    assert health.status() == "ready"
    health.close()
    health.sample_once()
    assert health.status() == "not_ready"


def test_blocked_probe_does_not_block_http_or_create_threads(tmp_path):
    app = create_http_app(tmp_path / "local.sqlite", settings=_local_settings())
    entered, release = Event(), Event()

    def blocked():
        entered.set()
        assert release.wait(2)
        return True

    health = app.state.health
    health.check = blocked
    try:
        with TestClient(app) as client:
            assert entered.wait(1)
            thread = health.thread
            started = monotonic()
            for _ in range(20):
                assert client.get("/health/live").status_code == 200
                assert client.get("/health/ready").status_code == 503
            assert monotonic() - started < 1
            assert health.thread is thread
            release.set()
    finally:
        release.set()
    assert not health.running


def test_cloud_epoch_probe_reuses_task_io_budget_and_namespace(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from agent_storage import PostgresControlPlaneStores
    from agent_storage.postgres.task_io import current_task_io_deadline
    from zebra_agent_api import health_readiness as module

    stores = Mock(spec=PostgresControlPlaneStores)
    stores.deployment_namespace = "owned-test-namespace"
    api = SimpleNamespace(
        stores=stores, settings=SimpleNamespace(deployment="cloud", database_url="test-dsn")
    )
    seen = []

    def read(dsn, *, deployment_namespace):
        assert dsn == "test-dsn" and deployment_namespace == "owned-test-namespace"
        assert 0 < current_task_io_deadline() - monotonic() <= 0.75
        seen.append(True)

    monkeypatch.setattr(module, "read_control_plane_epoch", read)
    health = ApiHealth(api)
    health.sample_once()
    assert health.status() == "ready" and seen == [True]

    def unavailable(*args, **kwargs):
        raise TimeoutError("bounded dependency unavailable")

    monkeypatch.setattr(module, "read_control_plane_epoch", unavailable)
    health.sample_once()
    assert health.status() == "not_ready"
    assert current_task_io_deadline() is None


def test_startup_dependency_failure_never_starts_or_readies_probe(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import pytest
    from zebra_agent_api import host_auth

    async def unavailable(_):
        raise RuntimeError("startup dependency unavailable")

    monkeypatch.setattr(host_auth, "warm_host_grant_keys", unavailable)
    api = SimpleNamespace(
        settings=SimpleNamespace(deployment="cloud"),
        stream_v2_reader=None,
        stream_notifications=None,
    )
    health = ApiHealth(api, check=lambda: True)

    async def enter():
        with pytest.raises(RuntimeError, match="startup dependency"):
            async with health.lifespan(None):
                raise AssertionError("failed startup must not serve")

    asyncio.run(enter())
    assert not health.running and health.status() == "not_ready"
