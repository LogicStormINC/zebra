"""Native consumer lock contract on the formal PostgreSQL schema."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from threading import Event, Lock
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage.postgres.host_management import HostManagementStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.publication_config import load_publication_approval
from zebra_agent_api.publication_consumer import resolve_consumer_binding
from zebra_agent_api.responses import ApiResponse

from tests.api.test_publication_management import (
    PATH,
    evidence,
    host_management_dsn,  # noqa: F401
    materialize,
    publisher,  # noqa: F401
)


@pytest.fixture
def consumer(publisher):  # noqa: F811
    p = publisher
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as client:
        request = materialize(p)
        response = client.post(PATH, headers=p.headers, json=request)
        assert response.status_code == 200, response.text
        version = response.json()["result"]
        publish = {
            "action": "publish",
            "operationId": str(uuid4()),
            "expectedRevision": 1,
            "versionId": request["versionId"],
            "evidenceId": evidence(p, version),
        }
        response = client.post(PATH, headers=p.headers, json=publish)
        assert response.status_code == 200, response.text
        context = HostContextEnvelope(
            grant_id="synthetic",
            host_app_id=p.approval["consumer_hosts"][0],
            namespace_id="local",
            workspace_ref="workspace://synthetic",
            resource_refs=(
                HostResourceRef(type="principal", id="synthetic"),
                HostResourceRef(type="thread", id=str(uuid4())),
            ),
            scopes=("agent.run",),
            limits=HostTechnicalLimits(
                max_runtime_seconds=300, max_model_tokens=10000, max_artifact_bytes=1048576
            ),
            origin=p.scope.authority_issuer,
            policy_version="user/1",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        verified = VerifiedHostGrant(
            context, "synthetic", JwtAlgorithm.RS256, p.scope.authority_issuer, "synthetic"
        )
        parsed = {
            "definition_id": str(p.scope.definition_id),
            "definition_environment": p.approval["scope"]["environment"],
        }
        yield SimpleNamespace(
            p=p,
            client=client,
            request=request,
            version=version,
            publish=publish,
            context=context,
            verified=verified,
            parsed=parsed,
        )


def consume(env):
    return resolve_consumer_binding(
        env.p.cfg, env.p.registry, env.parsed, env.context, env.verified
    )


def wait_blocker(dsn, *, timeout=2):
    """Observe the actual blocked PID/lock; never infer blocking from a sleep."""
    end = monotonic() + timeout
    with psycopg.connect(dsn, autocommit=True) as observer:
        while monotonic() < end:
            rows = observer.execute(
                "SELECT a.pid,pg_blocking_pids(a.pid),l.classid,l.objid,l.objsubid,l.mode "
                "FROM pg_stat_activity a JOIN pg_locks l USING(pid) "
                "WHERE a.datname=current_database() AND l.locktype='advisory' AND NOT l.granted"
            ).fetchall()
            if rows:
                return rows
            sleep(0.01)
    raise AssertionError("no blocked advisory-lock backend observed")


def test_two_actual_consumers_can_resolve_together(consumer, monkeypatch):
    env = consumer
    original = env.p.registry.resolve_published
    first, both, release = Event(), Event(), Event()
    guard, arrivals = Lock(), []

    def held(*args, **kwargs):
        with guard:
            arrivals.append(1)
            first.set()
            if len(arrivals) == 2:
                both.set()
        assert release.wait(3), "consumer was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(env.p.registry, "resolve_published", held)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(consume, env)
        assert first.wait(2)
        b = pool.submit(consume, env)
        try:
            assert both.wait(1), "second consumer serialized behind exclusive read locks"
        finally:
            release.set()
        assert not isinstance(a.result(3), ApiResponse)
        assert not isinstance(b.result(3), ApiResponse)


@pytest.mark.parametrize("writer", ["rotate", "publish", "legacy_release"])
def test_actual_writers_wait_then_new_consumer_sees_change(consumer, monkeypatch, writer):
    env, entered, release = consumer, Event(), Event()
    original = env.p.registry.resolve_published
    snapshot = consume(env)
    assert not isinstance(snapshot, ApiResponse)
    trust = load_publication_approval(str(env.p.path), "local").trust

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(env.p.registry, "resolve_published", held)
    if writer == "rotate":
        action = partial(
            HostManagementStore(env.p.cfg.database_url, deployment_namespace="local").approve,
            replace(trust, revision=2, fingerprint="b" * 64),
            1,
        )
    elif writer == "publish":
        request = {**materialize(env.p), "expectedRevision": 2, "version": 2}
        materialized = env.client.post(PATH, headers=env.p.headers, json=request)
        assert materialized.status_code == 200, materialized.text
        change = {
            **env.publish,
            "operationId": str(uuid4()),
            "expectedRevision": 3,
            "versionId": request["versionId"],
            "evidenceId": evidence(env.p, materialized.json()["result"]),
        }
        action = partial(env.client.post, PATH, headers=env.p.headers, json=change)
    else:
        from agent_core.domain.agent_definitions import AgentRelease
        from agent_core.domain.identifiers import AgentReleaseId

        version = env.p.registry.get_version(env.p.scope, UUID(env.request["versionId"]))
        change = AgentRelease.from_version(
            version,
            release_id=AgentReleaseId(uuid4()),
            environment=env.p.approval["scope"]["environment"],
            actor_ref="legacy",
            effective_at=datetime.now(UTC),
        )
        action = partial(env.p.registry.append_release, change)
    with ThreadPoolExecutor(2) as pool:
        reading = pool.submit(consume, env)
        assert entered.wait(2)
        writing = pool.submit(action)
        try:
            blocked = wait_blocker(env.p.cfg.database_url)
            assert blocked[0][1], blocked
            assert not writing.done()
        finally:
            release.set()
        assert not isinstance(reading.result(3), ApiResponse)
        result = writing.result(3)
        if writer == "publish":
            assert result.status_code == 200, result.text
    monkeypatch.setattr(env.p.registry, "resolve_published", original)
    following = consume(env)
    if writer == "rotate":
        assert isinstance(following, ApiResponse) and following.status_code == 403
    elif writer == "legacy_release":
        assert str(following.release_id) == str(change.release_id)
    else:
        assert str(following.bound_version.version_id) == change["versionId"]


def test_native_read_committed_timeout_releases_waiting_consumer(consumer):
    from agent_storage.postgres.host_management import _canonical
    from agent_storage.postgres.task_io import task_io_deadline

    env = consumer
    management = HostManagementStore(env.p.cfg.database_url, deployment_namespace="local")
    trust = load_publication_approval(str(env.p.path), "local").trust
    with psycopg.connect(env.p.cfg.database_url) as blocker:
        assert blocker.execute("SHOW transaction_isolation").fetchone() == ("read committed",)
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (_canonical(management._binding(trust)),),
        )
        start = monotonic()
        with task_io_deadline(start + 0.2):
            result = consume(env)
        assert isinstance(result, ApiResponse) and result.status_code == 503
        assert monotonic() - start < 1
    assert not isinstance(consume(env), ApiResponse)


def test_cancel_actual_consumer_releases_both_locks(consumer, monkeypatch):
    env, entered = consumer, Event()
    original = env.p.registry.resolve_published
    pid = []

    def blocked(*args, **kwargs):
        with env.p.registry._database.connect() as connection:
            assert (
                connection.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"]
                == "read committed"
            )
            pid.append(connection.info.backend_pid)
            entered.set()
            connection.execute("SELECT pg_sleep(10)")
        return original(*args, **kwargs)

    monkeypatch.setattr(env.p.registry, "resolve_published", blocked)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(consume, env)
        assert entered.wait(2)
        with psycopg.connect(env.p.cfg.database_url, autocommit=True) as observer:
            until = monotonic() + 2
            while monotonic() < until:
                waiting = observer.execute(
                    "SELECT wait_event FROM pg_stat_activity WHERE pid=%s", (pid[0],)
                ).fetchone()
                if waiting == ("PgSleep",):
                    break
                sleep(0.01)
            else:
                raise AssertionError("consumer never reached cancellable query")
            assert observer.execute("SELECT pg_cancel_backend(%s)", (pid[0],)).fetchone() == (True,)
        with pytest.raises(psycopg.errors.QueryCanceled):
            pending.result(3)
    monkeypatch.setattr(env.p.registry, "resolve_published", original)
    assert not isinstance(consume(env), ApiResponse)


def test_expired_approval_during_actual_consume_is_rejected(consumer, monkeypatch):
    from tests.api.test_bundle_management import write

    env = consumer
    approval = {
        **env.p.approval,
        "trust_revision": 2,
        "expires_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    }
    write(env.p.path, approval)
    trust = load_publication_approval(str(env.p.path), "local").trust
    HostManagementStore(env.p.cfg.database_url, deployment_namespace="local").approve(trust, 1)
    original = env.p.registry.resolve_published

    def expires(*args, **kwargs):
        result = original(*args, **kwargs)
        with env.p.registry._database.connect() as connection:
            connection.execute("SELECT pg_sleep(1.1)")
        return result

    monkeypatch.setattr(env.p.registry, "resolve_published", expires)
    result = consume(env)
    assert isinstance(result, ApiResponse) and result.status_code in {403, 503}


def test_consumer_permission_removed_during_read_is_rechecked(consumer, monkeypatch):
    from tests.api.test_bundle_management import write

    env = consumer
    original = env.p.registry.resolve_published

    def revoked(*args, **kwargs):
        result = original(*args, **kwargs)
        write(env.p.path, {**env.p.approval, "consumer_hosts": []})
        return result

    monkeypatch.setattr(env.p.registry, "resolve_published", revoked)
    result = consume(env)
    assert isinstance(result, ApiResponse) and result.status_code == 403
    monkeypatch.setattr(env.p.registry, "resolve_published", original)
    following = consume(env)
    assert isinstance(following, ApiResponse) and following.status_code == 403
