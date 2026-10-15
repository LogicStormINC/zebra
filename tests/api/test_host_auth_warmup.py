"""Startup warms only public keys; every request still checks fresh authority."""

import asyncio
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace

import jwt
import pytest
from agent_security import CachingJwksKeyResolver, HostGrantBindingError, PyJwtHostGrantDecoder
from zebra_agent_api import host_auth
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer

from tests.agent_security.test_jwks_bounds import jwks_server
from tests.api.test_host_auth_bounds import Registry
from tests.api.test_host_auth_http import _cloud_client, _FakeHostAuthorizer
from tests.api.test_postgres_host_auth_authorizer import _claims

native_jwks = jwks_server


def test_cloud_lifespan_warms_before_serving(tmp_path, monkeypatch):
    seen = []

    async def warm(authorizer):
        seen.append(authorizer)

    monkeypatch.setattr(host_auth, "warm_host_grant_keys", warm, raising=False)
    authorizer = _FakeHostAuthorizer()
    with _cloud_client(tmp_path, authorizer) as client:
        assert seen == [authorizer]
        assert client.get("/health").status_code == 200


def test_native_warmup_never_caches_authority(native_jwks):
    uri, key, calls, _, _ = native_jwks
    registry = Registry()
    registry.record = replace(registry.record, jwks_uri=uri + "/keys")
    registry.list_registries = lambda: (registry.record, registry.record)
    resolver = CachingJwksKeyResolver()
    authorizer = PostgresHostGrantRequestAuthorizer(registry, PyJwtHostGrantDecoder(resolver))
    asyncio.run(host_auth.warm_host_grant_keys(authorizer))
    assert calls == ["/keys"] and registry.reads == registry.consumed == []
    request = SimpleNamespace(
        method="GET", path="/sessions", origin="https://trench.example.com",
        deadline=monotonic() + 1, before_consume=None,
    )
    for jti in ("first", "second"):
        request.authorization = "Bearer " + jwt.encode(
            _claims(jti), key, algorithm="RS256", headers={"kid": "current"},
        )
        assert authorizer.authorize(request)
    assert len(registry.reads) == len(registry.consumed) == 2
    assert calls == ["/keys"]
    registry.record = replace(registry.record, active=False)
    with pytest.raises(HostGrantBindingError):
        authorizer.authorize(request)
    assert len(registry.reads) == 3 and len(registry.consumed) == 2


def test_warmup_failure_remains_optional_and_logs_no_detail(caplog):
    registry = Registry()

    def unavailable():
        raise TimeoutError("private error detail must not reach logs")

    registry.list_registries = unavailable
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry, PyJwtHostGrantDecoder(CachingJwksKeyResolver()),
    )
    asyncio.run(host_auth.warm_host_grant_keys(authorizer))
    assert registry.consumed == []
    assert "TimeoutError" in caplog.text and "private error detail" not in caplog.text
    asyncio.run(host_auth.warm_host_grant_keys(_FakeHostAuthorizer()))
    asyncio.run(host_auth.warm_host_grant_keys(None))
