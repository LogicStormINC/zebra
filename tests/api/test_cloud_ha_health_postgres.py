"""Opt-in real, owned PostgreSQL health acceptance; no business/model replay."""

import json
import os
import subprocess
from dataclasses import replace
from time import monotonic, sleep
from uuid import uuid4

import psycopg
import pytest
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.postgres.migration_types import PostgresMigrationError
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from zebra_agent_api import create_http_app

from tests.api.test_host_auth_http import _cloud_settings, _FakeHostAuthorizer
from tests.test_cloud_api_worker_profile_composition import _cloud_settings as cloud_bundle

pytestmark = pytest.mark.skipif(
    os.environ.get("ZEBRA_HA_POSTGRES_ACCEPTANCE") != "1", reason="explicit owned PG opt-in"
)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=30).strip()


def await_value(check, expected, *, seconds=5):
    until = monotonic() + seconds
    while monotonic() < until:
        if check() == expected:
            return
        sleep(0.05)
    assert check() == expected


@pytest.fixture(scope="module")
def owned_pg():
    name = "ca-ha-02-pg-" + uuid4().hex[:12]
    # ponytail: one capped PG, ephemeral tmpfs; not a cluster/production HA proof.
    container = docker(
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "codex.owner=ca-ha-02-pg-acceptance",
        "--cpus=1",
        "--memory=512m",
        "--pids-limit=128",
        "--tmpfs",
        "/var/lib/postgresql/data:rw,size=268435456",
        "-e",
        "POSTGRES_PASSWORD=disposable",
        "-p",
        "127.0.0.1::5432",
        "--pull=never",
        "postgres:17-alpine",
        "-c",
        "max_connections=16",
        "-c",
        "shared_buffers=32MB",
    )
    try:
        limits = json.loads(docker("inspect", "--format", "{{json .HostConfig}}", container))
        assert limits["NanoCpus"] == 1_000_000_000
        assert limits["Memory"] == 512 * 1024 * 1024
        assert limits["PidsLimit"] == 128
        assert "/var/lib/postgresql/data" in limits["Tmpfs"]
        port = docker("port", container, "5432/tcp").split(":")[-1]
        admin = make_conninfo(
            host="127.0.0.1",
            port=port,
            dbname="postgres",
            user="postgres",
            password="disposable",
            connect_timeout=1,
        )

        def available():
            try:
                with psycopg.connect(admin):
                    return True
            except psycopg.OperationalError:
                return False

        await_value(available, True, seconds=20)
        apply_postgres_migrations(admin)
        with psycopg.connect(admin) as c:
            c.execute("CREATE ROLE ha_probe LOGIN PASSWORD 'disposable' CONNECTION LIMIT 1")
            c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO ha_probe")
        probe = make_conninfo(admin, user="ha_probe")
        yield admin, probe, container
    finally:
        # Exact UUID-owned container, including anonymous mounts if any, on failures too.
        docker("rm", "-fv", container)


def app_for(tmp_path, admin, probe):
    namespace = "ha-02-" + uuid4().hex
    bootstrap_control_plane_epoch(admin, deployment_namespace=namespace)
    bundle = replace(cloud_bundle(), dsn=probe, deployment_namespace=namespace)
    return create_http_app(
        tmp_path / "unused.sqlite",
        settings=_cloud_settings(probe),
        cloud_composition=bundle,
        host_grant_authorizer=_FakeHostAuthorizer(),
    )


def ready(client):
    response = client.get("/health/ready")
    assert response.json() in ({"status": "ready"}, {"status": "not_ready"})
    assert response.headers["cache-control"] == "no-store"
    return response.status_code


def assert_live(client):
    started = monotonic()
    for _ in range(10):
        response = client.get("/health/live")
        assert response.status_code == 200 and response.json() == {"status": "alive"}
    assert monotonic() - started < 1


def test_real_epoch_http_loss_recovery_and_shutdown(owned_pg, tmp_path):
    admin, probe, container = owned_pg
    app = app_for(tmp_path, admin, probe)
    with TestClient(app) as client:
        await_value(lambda: ready(client), 200)
        assert client.get("/health").status_code == 200
        assert client.get("/sessions/not-authorized").status_code == 401
        with psycopg.connect(admin) as c:
            before = c.execute(
                "SELECT * FROM control_plane_epochs ORDER BY deployment_namespace"
            ).fetchall()
        docker("pause", container)
        try:
            await_value(lambda: ready(client), 503, seconds=3)
            assert_live(client)
        finally:
            docker("unpause", container)
        await_value(lambda: ready(client), 200, seconds=15)
        with psycopg.connect(admin) as c:
            assert (
                c.execute(
                    "SELECT * FROM control_plane_epochs ORDER BY deployment_namespace"
                ).fetchall()
                == before
            )
        assert app.state.health.running
    assert not app.state.health.running
    assert app.state.health.status() == "not_ready"


def test_real_connection_exhaustion_and_recovery(owned_pg, tmp_path):
    admin, probe, _ = owned_pg
    app = app_for(tmp_path, admin, probe)
    with TestClient(app) as client:
        await_value(lambda: ready(client), 200)
        with psycopg.connect(probe):  # Exhaust the actual non-superuser role slot.
            await_value(lambda: ready(client), 503, seconds=3)
            assert_live(client)
        await_value(lambda: ready(client), 200)
    assert not app.state.health.running


def test_real_query_block_has_deadline_and_leaves_no_probe_session(owned_pg, tmp_path):
    admin, probe, _ = owned_pg
    app = app_for(tmp_path, admin, probe)
    with TestClient(app) as client:
        await_value(lambda: ready(client), 200)
        with psycopg.connect(admin) as blocker:
            blocker.execute("LOCK TABLE control_plane_epochs IN ACCESS EXCLUSIVE MODE")
            await_value(lambda: ready(client), 503, seconds=3)
            assert_live(client)
        await_value(lambda: ready(client), 200)
    with psycopg.connect(admin) as c:
        assert c.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE usename='ha_probe'"
        ).fetchone() == (0,)
    assert not app.state.health.running


def test_real_incompatible_schema_refuses_factory_before_probe(owned_pg, tmp_path):
    admin, probe, _ = owned_pg
    with psycopg.connect(admin) as c:
        row = c.execute(
            "SELECT version,name FROM zebra_schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        c.execute(
            "UPDATE zebra_schema_migrations SET name='ha-incompatible' WHERE version=%s", (row[0],)
        )
    try:
        with pytest.raises(PostgresMigrationError):
            app_for(tmp_path, admin, probe)
    finally:
        with psycopg.connect(admin) as c:
            c.execute(
                "UPDATE zebra_schema_migrations SET name=%s WHERE version=%s", (row[1], row[0])
            )


def test_worker_observation_uses_real_pg_capability_expiry(owned_pg, tmp_path):
    from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities
    from zebra_agent_worker.worker_health import WorkerHealth, read_worker_health

    admin, _, _ = owned_pg
    namespace = "ha-worker-" + uuid4().hex
    bootstrap_control_plane_epoch(admin, deployment_namespace=namespace)
    store = PostgresWorkerCapabilities(admin, deployment_namespace=namespace)
    lease = store.register(uuid4(), configuration_digest="a" * 64, ttl_seconds=1)
    health = WorkerHealth()
    path = tmp_path / "worker-health.json"
    try:
        health.attach(path)
        health.command_tick(lease, monotonic())
        initial = health.snapshot()
        assert initial["ready"]
        sleep(1.05)
        assert store.current(configuration_digest="a" * 64) == ()
        assert not health.snapshot()["ready"]
        assert not read_worker_health(
            path, initial["pid"], initial["instance_id"], now=monotonic()
        )["ready"]
    finally:
        health.close()
        store.revoke(lease)
