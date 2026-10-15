"""Only catalog reads have room for the existing five-second cold key fetch."""

from time import monotonic
from types import SimpleNamespace

import jwt
import pytest
from agent_security import CachingJwksKeyResolver, PyJwtHostGrantDecoder
from cryptography.hazmat.primitives.asymmetric import rsa
from zebra_agent_api import host_auth
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer

from tests.api.test_host_auth_bounds import Key, Registry
from tests.api.test_host_auth_http import _cloud_client, _FakeHostAuthorizer
from tests.api.test_postgres_host_auth_authorizer import _claims


@pytest.mark.parametrize(
    "path,minimum,maximum",
    [
        ("/v1/extensions/skill-installations", 4, 5),
        ("/v1/extensions/mcp-connections", 4, 5),
        ("/sessions", 0, 2),
    ],
)
def test_http_catalog_budget_is_separate_from_execution_budget(tmp_path, path, minimum, maximum):
    authorizer = _FakeHostAuthorizer()
    with _cloud_client(tmp_path, authorizer) as client:
        start = monotonic()
        response = client.get(
            path,
            headers={
                "Origin": authorizer.allowed_origins[0],
                "Authorization": "Bearer valid-grant",
            },
        )
    assert response.status_code != 503
    deadline = authorizer.calls[-1].deadline
    assert minimum < deadline - start <= maximum + 0.1


@pytest.mark.parametrize("seconds", [1, 4])
def test_authorizer_preserves_supplied_catalog_deadline_and_fresh_consumption(seconds):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry, resolver = Registry(), Key(key.public_key())
    authorizer = PostgresHostGrantRequestAuthorizer(registry, PyJwtHostGrantDecoder(resolver))
    deadline = monotonic() + seconds
    request = SimpleNamespace(
        method="GET",
        path="/v1/extensions/skill-installations",
        origin="https://trench.example.com",
        deadline=deadline,
        before_consume=None,
        authorization="Bearer "
        + jwt.encode(_claims("catalog", scopes=["extensions.read"]), key, algorithm="RS256"),
    )
    assert authorizer.authorize(request)
    assert resolver.deadlines == [deadline]
    assert registry.reads[-1]["deadline"] == deadline
    assert registry.consumed[-1][1]["deadline"] == deadline


def test_public_key_warmup_has_its_existing_fetch_budget(monkeypatch):
    import asyncio

    registry, resolver, seen = Registry(), CachingJwksKeyResolver(), []
    registry.list_registries = lambda: (registry.record,)
    monkeypatch.setattr(resolver, "prefetch", lambda uri, *, deadline: seen.append(deadline))
    authorizer = PostgresHostGrantRequestAuthorizer(registry, PyJwtHostGrantDecoder(resolver))
    start = monotonic()
    asyncio.run(host_auth.warm_host_grant_keys(authorizer))
    assert 4 < seen[0] - start <= 5.1
    assert not registry.reads and not registry.consumed
