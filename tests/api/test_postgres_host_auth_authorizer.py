from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import jwt
import psycopg
import pytest
from agent_security import PyJwtHostGrantDecoder
from agent_storage import (
    HostRegistryRecord,
    PostgresHostAuthorityStore,
    apply_postgres_migrations,
    sqlite_control_plane_stores,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_api import create_http_app
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
from zebra_agent_config import ApiSettings, ModelSettings, RuntimeSettings, ZebraAgentSettings


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"host_authorizer_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _settings(database_url: str) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="cloud",
        database_url=database_url,
        api=ApiSettings(auth_token="must-not-be-used"),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        runtime=RuntimeSettings(
            runtime_class="gvisor",
            image="registry.example/zebra@sha256:" + "a" * 64,
            require_workspace_quota=True,
        ),
    )


def _registry() -> HostRegistryRecord:
    return HostRegistryRecord(
        host_app_id="trench",
        namespace_id="tenant-a",
        issuer="https://api.trench.example.com",
        audience="zebra-embedded",
        jwks_uri="https://api.trench.example.com/.well-known/jwks.json",
        allowed_origins=("https://trench.example.com",),
        algorithms=("RS256",),
        policy_version="policy-v1",
    )


def _claims(
    jti: str, *, scopes: list[str] | None = None, exp: int | None = None
) -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    return {
        "iss": "https://api.trench.example.com",
        "aud": "zebra-embedded",
        "sub": "opaque-subject",
        "jti": jti,
        "iat": now - 1,
        "nbf": now - 1,
        "exp": exp if exp is not None else now + 300,
        "host_app_id": "trench",
        "namespace_id": "tenant-a",
        "workspace_ref": "workspace-a",
        "resource_refs": [{"type": "trench.event", "id": "evt-1"}],
        "scopes": scopes if scopes is not None else ["agent.run", "trench.event.read"],
        "limits": {
            "max_runtime_seconds": 300,
            "max_model_tokens": 100_000,
            "max_artifact_bytes": 10_485_760,
        },
        "origin": "https://trench.example.com",
        "policy_version": "policy-v1",
    }


def test_real_signed_grant_replay_scope_origin_and_audit_matrix(dsn: str, tmp_path: Path) -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    registry = PostgresHostAuthorityStore(dsn, deployment_namespace="deployment-a")
    registry.upsert_registry(_registry())
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry,
        decoder=PyJwtHostGrantDecoder(_StaticResolver(private_key.public_key())),
    )
    client = TestClient(
        create_http_app(
            tmp_path / "api.sqlite",
            settings=_settings("postgresql://zebra@example/zebra"),
            stores=sqlite_control_plane_stores(tmp_path / "stores.sqlite"),
            host_grant_authorizer=authorizer,
        )
    )

    valid = jwt.encode(_claims("accepted-1"), private_key, algorithm="RS256")
    first = client.get(
        "/sessions/not-a-valid-uuid",
        headers={"Authorization": f"Bearer {valid}", "Origin": "https://trench.example.com"},
    )
    replay = client.get(
        "/sessions/not-a-valid-uuid",
        headers={"Authorization": f"Bearer {valid}", "Origin": "https://trench.example.com"},
    )
    assert first.status_code == 400
    assert replay.status_code == 403

    wrong_scope = jwt.encode(
        _claims("scope-1", scopes=["trench.event.read"]),
        private_key,
        algorithm="RS256",
    )
    wrong_scope_response = client.get(
        "/sessions/not-a-valid-uuid",
        headers={"Authorization": f"Bearer {wrong_scope}", "Origin": "https://trench.example.com"},
    )
    assert wrong_scope_response.status_code == 403

    wrong_origin = client.get(
        "/sessions/not-a-valid-uuid",
        headers={"Authorization": f"Bearer {valid}", "Origin": "https://evil.example.com"},
    )
    assert wrong_origin.status_code == 403

    audit = registry.list_audit(issuer=_registry().issuer, jti="accepted-1")
    assert [record.outcome for record in audit] == ["accepted", "replay"]
    scope_audit = registry.list_audit(issuer=_registry().issuer, jti="scope-1")
    assert [record.outcome for record in scope_audit] == ["rejected"]
    assert all(record.grant_digest != valid for record in (*audit, *scope_audit))


class _StaticResolver:
    def __init__(self, key: object) -> None:
        self.key = key

    def resolve(self, jwks_uri: str, token: str) -> object:
        assert jwks_uri.startswith("https://")
        assert token
        return self.key
