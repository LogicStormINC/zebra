"""Pre-consumption authority identity and cumulative deadline regressions."""

from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from typing import cast

import jwt
import pytest
from agent_security import HostGrantBindingError, PyJwtHostGrantDecoder
from cryptography.hazmat.primitives.asymmetric import rsa
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
from zebra_agent_api.http import HostGrantHttpRequest

from tests.api.test_postgres_host_auth_authorizer import _claims, _registry


class Registry:
    def __init__(self):
        self.record = _registry()
        self.consumed = []
        self.reads = []

    def list_registries(self, **kwargs):
        pytest.fail("request authentication must not scan registries")

    def get_registry(self, **kwargs):
        self.reads.append(kwargs)
        return self.record

    def consume_grant(self, attempt, **kwargs):
        self.consumed.append((attempt, kwargs))
        return SimpleNamespace(accepted=True)

    def record_rejection(self, *args, **kwargs):
        pass


class Key:
    def __init__(self, key):
        self.key = key
        self.deadlines = []

    def resolve(self, uri, token, *, deadline=None):
        self.deadlines.append(deadline)
        return self.key


def setup_request(**overrides):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry = Registry()
    resolver = Key(key.public_key())
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry, decoder=PyJwtHostGrantDecoder(resolver)
    )
    request = SimpleNamespace(
        method="GET",
        path="/sessions",
        origin="https://trench.example.com",
        authorization="Bearer " + jwt.encode(_claims("bounded"), key, algorithm="RS256"),
        deadline=monotonic() + 1,
        before_consume=None,
    )
    request.__dict__.update(overrides)
    return authorizer, registry, resolver, cast(HostGrantHttpRequest, request)


def test_exact_candidate_and_one_deadline_reach_decoder_hook_and_consumption():
    authorizer, registry, resolver, request = setup_request()
    seen = []
    request.before_consume = lambda verified: seen.append(verified.context.namespace_id)
    result = authorizer.authorize(request)
    assert result.context.namespace_id == "tenant-a"
    assert seen == ["tenant-a"]
    assert registry.reads == [
        {
            "host_app_id": "trench",
            "namespace_id": "tenant-a",
            "deadline": request.deadline,
        }
    ]
    assert resolver.deadlines == [request.deadline]
    assert registry.consumed[0][1] == {
        "expected_registry": registry.record,
        "deadline": request.deadline,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace_id", "tenant-b"),
        ("host_app_id", "other"),
        ("issuer", "https://other.example.com"),
        ("active", False),
    ],
)
def test_wrong_candidate_identity_never_consumes(field, value):
    authorizer, registry, _, request = setup_request()
    registry.record = replace(registry.record, **{field: value})
    with pytest.raises(HostGrantBindingError):
        authorizer.authorize(request)
    assert registry.consumed == []


def test_target_denial_preserves_original_exception_and_does_not_consume():
    authorizer, registry, _, request = setup_request()
    original = LookupError("target denied")

    def denied(verified):
        raise original

    request.before_consume = denied
    with pytest.raises(LookupError) as caught:
        authorizer.authorize(request)
    assert caught.value is original
    assert registry.consumed == []


def test_expired_budget_and_oversized_token_do_not_read_registry():
    for override in ({"deadline": monotonic() - 1}, {"authorization": "Bearer " + "x" * 32769}):
        authorizer, registry, _, request = setup_request(**override)
        with pytest.raises((TimeoutError, HostGrantBindingError)):
            authorizer.authorize(request)
        assert registry.reads == []
        assert registry.consumed == []


def test_unknown_consumption_outcome_is_not_retried_or_replaced():
    authorizer, registry, _, request = setup_request()
    original = TimeoutError("unknown COMMIT")
    calls = []

    def unknown(*args, **kwargs):
        calls.append(1)
        raise original

    registry.consume_grant = unknown
    with pytest.raises(TimeoutError) as caught:
        authorizer.authorize(request)
    assert caught.value is original
    assert calls == [1]


@pytest.mark.parametrize(
    "path,method",
    [
        ("/agui/commands", "POST"),
        ("/agui/threads/task/runs/run/stream", "GET"),
        ("/tasks/task/cancel", "POST"),
        ("/sessions/session", "GET"),
        ("/tasks", "POST"),
        ("/sessions", "POST"),
    ],
)
def test_target_routes_without_hook_cannot_consume(path, method):
    authorizer, registry, _, request = setup_request(path=path, method=method)
    with pytest.raises(HostGrantBindingError, match="target validation"):
        authorizer.authorize(request)
    assert registry.consumed == []


def test_late_target_hook_does_not_consume():
    authorizer, registry, _, request = setup_request()
    request.deadline = monotonic() + 0.08
    entered = []

    def late(verified):
        entered.append(True)
        while monotonic() < request.deadline:
            pass

    request.before_consume = late
    with pytest.raises(TimeoutError):
        authorizer.authorize(request)
    assert registry.consumed == []
    assert entered == [True]
