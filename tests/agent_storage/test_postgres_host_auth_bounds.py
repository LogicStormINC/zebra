"""Native auth store bounds, immutable candidates and atomic/unknown commits."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import jwt
import psycopg
import pytest
from agent_security import CachingJwksKeyResolver, HostGrantDecodeError, PyJwtHostGrantDecoder
from agent_storage import PostgresHostAuthorityStore
from agent_storage.postgres.host_auth import HostGrantConsumptionUnknown
from agent_storage.postgres.host_auth_migration import HOST_AUTH_MIGRATION
from agent_storage.postgres.task_io import TaskIoConnection, task_io_deadline
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
from zebra_agent_api.http import HostGrantHttpRequest

from tests.agent_security.test_jwks_bounds import jwks_server as _jwks_server
from tests.agent_storage.test_postgres_host_auth import _attempt, _registry
from tests.api.test_postgres_host_auth_authorizer import _claims

jwks_server = _jwks_server


@pytest.fixture
def scratch():
    configured = os.environ.get("ZEBRA_HEADER_SCRATCH_DSN")
    if not configured:
        pytest.skip("isolated header_scratch DSN required")
    params = conninfo_to_dict(configured)
    assert params["dbname"] == "header_scratch"
    assert params["host"] in ("127.0.0.1", "localhost")
    schema = "grant_bounds_" + uuid4().hex
    with psycopg.connect(configured) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(configured, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(dsn) as setup:
            for statement in HOST_AUTH_MIGRATION.statements:
                setup.execute(statement)
        store = PostgresHostAuthorityStore(dsn, deployment_namespace="grant-bounds")
        store.upsert_registry(_registry())
        yield dsn, store
    finally:
        with psycopg.connect(configured) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("audience", "other-audience"),
        ("jwks_uri", "https://other.example.com/keys"),
        ("policy_version", "new-policy"),
        ("active", False),
    ],
)
def test_changed_candidate_is_not_consumed_and_denial_is_atomic(scratch, field, value):
    dsn, store = scratch
    candidate = store.get_registry(host_app_id="trench", namespace_id="tenant-a")
    store.upsert_registry(replace(candidate, **{field: value}))
    decision = store.consume_grant(_attempt(), expected_registry=candidate)
    assert not decision.accepted and decision.outcome == "rejected"
    assert [
        record.outcome for record in store.list_audit(issuer=candidate.issuer, jti="grant-1")
    ] == ["rejected"]
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)


def test_native_registry_lock_deadline_closes_and_never_consumes(scratch, monkeypatch):
    dsn, store = scratch
    seen = []
    execute = TaskIoConnection.execute

    def capture(self, *args, **kwargs):
        seen.append(self)
        return execute(self, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", capture)
    with psycopg.connect(dsn) as holder:
        holder.execute("UPDATE host_authority_registries SET active=false")
        started = monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            store.consume_grant(_attempt(), deadline=started + 0.3)
        assert monotonic() - started < 0.6
    assert seen and all(connection.closed for connection in seen)
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (0,)


def test_native_unique_jti_lock_is_bounded(scratch):
    dsn, store = scratch
    with psycopg.connect(dsn) as holder:
        holder.execute(
            """INSERT INTO host_grant_replay_ledger
            (deployment_namespace,issuer,jti,host_app_id,namespace_id,algorithm,
             grant_digest,scopes_digest,resource_digest,expires_at)
            VALUES('grant-bounds',%s,'grant-1','trench','tenant-a','RS256',%s,%s,%s,%s)""",
            (_attempt().issuer, "a" * 64, "b" * 64, "c" * 64, _attempt().expires_at),
        )
        with pytest.raises(psycopg.errors.LockNotAvailable):
            store.consume_grant(_attempt(), deadline=monotonic() + 0.3)
    assert store.list_audit(issuer=_attempt().issuer, jti="grant-1") == ()


def test_native_deferred_commit_rolls_back_jti_and_audit(scratch, monkeypatch):
    dsn, store = scratch
    with psycopg.connect(dsn) as setup:
        setup.execute("""CREATE FUNCTION delay_grant_commit() RETURNS trigger AS $$
            BEGIN PERFORM pg_sleep(3); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER delayed_grant_commit
            AFTER INSERT ON host_grant_audit DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION delay_grant_commit()""")
    seen = []
    execute = TaskIoConnection.execute

    def capture(self, *args, **kwargs):
        seen.append(self)
        return execute(self, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", capture)
    started = monotonic()
    with pytest.raises(TimeoutError):
        store.consume_grant(_attempt(), deadline=started + 0.35)
    assert monotonic() - started < 0.7
    assert seen and all(connection.closed for connection in seen)
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (0,)


@pytest.mark.parametrize(
    "fault",
    [
        psycopg.OperationalError,
        psycopg.errors.ConnectionFailure,
        psycopg.errors.TransactionResolutionUnknown,
        psycopg.errors.StatementCompletionUnknown,
    ],
)
def test_native_commit_success_but_unknown_reply_is_never_retried(scratch, monkeypatch, fault):
    dsn, store = scratch
    original_exit = TaskIoConnection.__exit__
    calls = []

    def lost_reply(self, *args):
        original_exit(self, *args)
        calls.append(1)
        raise fault("injected lost COMMIT acknowledgement")

    monkeypatch.setattr(TaskIoConnection, "__exit__", lost_reply)
    with pytest.raises(TimeoutError, match="consumption outcome") as caught:
        store.consume_grant(_attempt())
    assert type(caught.value).__name__ == "HostGrantConsumptionUnknown"
    assert isinstance(caught.value.__cause__, psycopg.OperationalError)
    assert calls == [1]
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (1,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (1,)


def test_native_backend_loss_during_actual_commit_is_typed_unknown_and_closed(scratch, monkeypatch):
    dsn, store = scratch
    with psycopg.connect(dsn) as setup:
        setup.execute("""CREATE FUNCTION wait_for_backend_loss() RETURNS trigger AS $$
            BEGIN PERFORM pg_sleep(3); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER wait_for_backend_loss
            AFTER INSERT ON host_grant_audit DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION wait_for_backend_loss()""")
    admitted = Event()
    connections = []
    execute = TaskIoConnection.execute

    def capture(self, query, *args, **kwargs):
        if "INSERT INTO host_grant_audit" in str(query):
            connections.append(self)
            admitted.set()
        return execute(self, query, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", capture)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(store.consume_grant, _attempt(), deadline=monotonic() + 1.5)
        assert admitted.wait(0.5)
        pid = connections[0].info.backend_pid
        with psycopg.connect(dsn, autocommit=True) as observer:
            deadline = monotonic() + 0.8
            while True:
                row = observer.execute(
                    "SELECT query,wait_event FROM pg_stat_activity WHERE pid=%s", (pid,)
                ).fetchone()
                if row == ("COMMIT", "PgSleep"):
                    break
                assert monotonic() < deadline, (
                    "the native COMMIT never entered its deferred trigger"
                )
                Event().wait(0.01)
            assert observer.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone() == (True,)
        with pytest.raises(HostGrantConsumptionUnknown) as caught:
            future.result(timeout=1)
    assert isinstance(caught.value.__cause__, psycopg.Error)
    assert len(connections) == 1 and connections[0].closed
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (0,)
        assert verify.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE pid=%s", (pid,)
        ).fetchone() == (0,)


def test_native_same_jti_atomic_winner_and_cumulative_reads(scratch, monkeypatch):
    dsn, store = scratch
    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(executor.map(store.consume_grant, [_attempt(), _attempt()]))
    assert sorted(decision.outcome for decision in decisions) == ["accepted", "replay"]
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (1,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (2,)
    execute = TaskIoConnection.execute
    seen = []

    def delayed(self, *args, **kwargs):
        seen.append(self)
        execute(self, "SELECT pg_sleep(0.15)")
        return execute(self, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", delayed)
    deadline = monotonic() + 0.28
    with pytest.raises(TimeoutError):
        with task_io_deadline(deadline):
            store.get_registry(host_app_id="trench", namespace_id="tenant-a", deadline=deadline)
            store.get_registry(host_app_id="trench", namespace_id="tenant-a", deadline=deadline)
    assert len(seen) == 2 and all(connection.closed for connection in seen)
    assert all(connection.deadline == deadline for connection in seen)


def test_native_grant_expiry_bounds_commit_not_only_preinsert_check(scratch):
    dsn, store = scratch
    with psycopg.connect(dsn) as setup:
        setup.execute("""CREATE FUNCTION delay_grant_expiry() RETURNS trigger AS $$
            BEGIN PERFORM pg_sleep(0.4); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER expire_during_commit
            AFTER INSERT ON host_grant_audit DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION delay_grant_expiry()""")
    attempt = replace(_attempt(), expires_at=datetime.now(UTC) + timedelta(seconds=0.18))
    with pytest.raises(TimeoutError):
        store.consume_grant(attempt)
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (0,)


def test_native_other_namespace_audience_and_jwks_are_not_substituted(scratch):
    dsn, store = scratch
    private_a = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_b = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    candidate_b = replace(
        _registry("tenant-b"), audience="audience-b", jwks_uri="https://keys-b.example/keys"
    )
    store.upsert_registry(candidate_b)
    resolved = []

    class Key:
        def resolve(self, uri, token, *, deadline=None):
            resolved.append(uri)
            return private_b.public_key() if uri == candidate_b.jwks_uri else private_a.public_key()

    claims = _claims("cross-namespace")
    claims["namespace_id"] = "tenant-b"
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=store, decoder=PyJwtHostGrantDecoder(Key())
    )
    request = HostGrantHttpRequest(
        method="GET",
        path="/sessions",
        origin="https://trench.example.com",
        authorization="Bearer " + jwt.encode(claims, private_a, algorithm="RS256"),
    )
    with pytest.raises(HostGrantDecodeError):
        authorizer.authorize(request)
    assert resolved == [candidate_b.jwks_uri]
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)


def test_native_registry_changes_in_target_hook_cannot_authorize(scratch):
    dsn, store = scratch
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Key:
        def resolve(self, uri, token, *, deadline=None):
            return private.public_key()

    def changed(verified):
        store.upsert_registry(replace(_registry(), audience="replacement"))

    request = SimpleNamespace(
        method="GET",
        path="/sessions",
        origin="https://trench.example.com",
        authorization="Bearer " + jwt.encode(_claims("raced"), private, algorithm="RS256"),
        deadline=monotonic() + 1,
        before_consume=changed,
    )
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=store, decoder=PyJwtHostGrantDecoder(Key())
    )
    from agent_security import HostGrantBindingError

    with pytest.raises(HostGrantBindingError, match="replay rejected"):
        authorizer.authorize(request)
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)
        assert verify.execute("SELECT outcome FROM host_grant_audit").fetchall() == [("rejected",)]


def test_actual_pg_jwks_target_and_commit_share_one_deadline(scratch, jwks_server, monkeypatch):
    dsn, store = scratch
    uri, private, calls, _, _ = jwks_server
    store.upsert_registry(replace(_registry(), jwks_uri=uri + "/delayed"))
    with psycopg.connect(dsn) as setup:
        setup.execute("""CREATE FUNCTION cumulative_commit() RETURNS trigger AS $$
            BEGIN PERFORM pg_sleep(0.25); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER cumulative_commit
            AFTER INSERT ON host_grant_audit DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION cumulative_commit()""")
    execute = TaskIoConnection.execute
    connections = []

    def delayed_registry(self, query, *args, **kwargs):
        connections.append(self)
        if "SELECT host_app_id" in str(query) and "FOR SHARE" not in str(query):
            execute(self, "SELECT pg_sleep(0.12)")
        return execute(self, query, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", delayed_registry)
    started = monotonic()
    deadline = started + 0.65

    def target(verified):
        with store._database.connect_task_io() as connection:
            connection.execute("SELECT pg_sleep(0.18)")

    request = SimpleNamespace(
        method="GET",
        path="/sessions",
        origin="https://trench.example.com",
        authorization="Bearer "
        + jwt.encode(_claims("cumulative"), private, algorithm="RS256", headers={"kid": "current"}),
        deadline=deadline,
        before_consume=target,
    )
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=store, decoder=PyJwtHostGrantDecoder(CachingJwksKeyResolver())
    )
    with pytest.raises(HostGrantConsumptionUnknown):
        authorizer.authorize(request)
    assert monotonic() - started < 1
    assert calls == ["/delayed"]
    assert connections and all(connection.closed for connection in connections)
    assert all(connection.deadline == deadline for connection in connections)
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (0,)


def test_native_confirmed_commit_rejection_preserves_sqlstate_not_unknown(scratch):
    dsn, store = scratch
    with psycopg.connect(dsn) as setup:
        setup.execute("""CREATE FUNCTION reject_commit() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'confirmed rejection'; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER reject_commit
            AFTER INSERT ON host_grant_audit DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION reject_commit()""")
    with pytest.raises(psycopg.errors.RaiseException) as caught:
        store.consume_grant(_attempt())
    assert caught.value.sqlstate == "P0001"
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT count(*) FROM host_grant_replay_ledger").fetchone() == (0,)
        assert verify.execute("SELECT count(*) FROM host_grant_audit").fetchone() == (0,)
