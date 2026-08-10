from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from agent_storage import (
    HostAuthorityStorageError,
    HostGrantAttempt,
    HostRegistryRecord,
    PostgresHostAuthorityStore,
    apply_postgres_migrations,
)
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"host_auth_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _registry(namespace: str = "tenant-a", *, active: bool = True) -> HostRegistryRecord:
    return HostRegistryRecord(
        host_app_id="trench",
        namespace_id=namespace,
        issuer="https://api.trench.example.com",
        audience="zebra-embedded",
        jwks_uri="https://api.trench.example.com/.well-known/jwks.json",
        allowed_origins=("https://trench.example.com",),
        algorithms=("RS256",),
        policy_version="trench-policy-v1",
        active=active,
    )


def _attempt(*, jti: str = "grant-1", namespace: str = "tenant-a") -> HostGrantAttempt:
    def digest(value: str) -> str:
        return sha256(value.encode()).hexdigest()

    return HostGrantAttempt(
        issuer="https://api.trench.example.com",
        jti=jti,
        host_app_id="trench",
        namespace_id=namespace,
        algorithm="RS256",
        grant_digest=digest(f"grant:{jti}"),
        scopes_digest=digest("agent.run,trench.event.read"),
        resource_digest=digest("trench.event:evt-1"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_host_registry_and_attempt_reject_untrusted_inputs() -> None:
    registry = _registry()
    with pytest.raises(HostAuthorityStorageError):
        HostRegistryRecord(**{**registry.__dict__, "issuer": "http://bad.example"})
    with pytest.raises(HostAuthorityStorageError):
        HostRegistryRecord(**{**registry.__dict__, "allowed_origins": ("*",)})
    with pytest.raises(HostAuthorityStorageError):
        HostRegistryRecord(**{**registry.__dict__, "algorithms": ("HS256",)})
    attempt = _attempt()
    with pytest.raises(HostAuthorityStorageError):
        HostGrantAttempt(**{**attempt.__dict__, "grant_digest": "raw-bearer-token"})


def test_constructor_does_not_run_ddl(postgres_dsn: str) -> None:
    schema = f"host_auth_no_ddl_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        store = PostgresHostAuthorityStore(isolated, deployment_namespace="deployment-a")
        with pytest.raises(errors.UndefinedTable):
            store.get_registry(host_app_id="trench", namespace_id="tenant-a")
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_registry_replay_audit_is_atomic_and_namespace_scoped(dsn: str) -> None:
    first = PostgresHostAuthorityStore(dsn, deployment_namespace="deployment-a")
    second = PostgresHostAuthorityStore(dsn, deployment_namespace="deployment-b")
    first.upsert_registry(_registry())
    second.upsert_registry(_registry())

    attempt = _attempt()
    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = tuple(executor.map(first.consume_grant, (attempt, attempt)))

    assert sorted(decision.accepted for decision in decisions) == [False, True]
    assert sorted(decision.outcome for decision in decisions) == ["accepted", "replay"]
    audit = first.list_audit(issuer=attempt.issuer, jti=attempt.jti)
    assert [record.outcome for record in audit] == ["accepted", "replay"]
    assert all(record.grant_digest == attempt.grant_digest for record in audit)
    assert all("token" not in record.reason.lower() for record in audit)

    with psycopg.connect(dsn) as connection:
        count = connection.execute(
            """
            SELECT count(*) FROM host_grant_replay_ledger
            WHERE deployment_namespace = %s AND issuer = %s AND jti = %s
            """,
            ("deployment-a", attempt.issuer, attempt.jti),
        ).fetchone()
    assert count == (1,)
    assert second.list_audit(issuer=attempt.issuer, jti=attempt.jti) == ()
    other_decision = second.consume_grant(_attempt(namespace="tenant-not-registered"))
    assert not other_decision.accepted
    assert other_decision.outcome == "rejected"
    assert second.list_audit(issuer=attempt.issuer, jti=other_decision.audit.jti)


def test_inactive_registry_and_expired_grant_are_audited_as_rejected(dsn: str) -> None:
    store = PostgresHostAuthorityStore(dsn, deployment_namespace="deployment-a")
    store.upsert_registry(_registry(active=False))
    inactive = store.consume_grant(_attempt())
    assert inactive.outcome == "rejected"
    assert "inactive" in inactive.audit.reason

    store.upsert_registry(_registry(active=True))
    base = _attempt(jti="expired")
    expired = HostGrantAttempt(
        **{**base.__dict__, "expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    decision = store.consume_grant(expired)
    assert decision.outcome == "rejected"
    assert decision.audit.outcome == "rejected"
