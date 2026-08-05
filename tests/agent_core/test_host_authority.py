from datetime import UTC, datetime

import pytest
from agent_core.domain.host_authority import (
    HostGrantExpiredError,
    HostGrantMismatchError,
    HostGrantNotYetValidError,
    HostGrantScopeError,
    HostResourceRef,
    HostSessionGrant,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
RESOURCE = {"type": "trench.event", "id": "evt_123"}


def make_grant(**overrides: object) -> HostSessionGrant:
    claims: dict[str, object] = {
        "iss": "https://api.trench.example.com",
        "aud": "zebra-embedded",
        "sub": "opaque-subject-ref",
        "jti": "grant_01",
        "iat": int(NOW.timestamp()) - 10,
        "nbf": int(NOW.timestamp()) - 10,
        "exp": int(NOW.timestamp()) + 300,
        "host_app_id": "trench",
        "namespace_id": "opaque-namespace-ref",
        "workspace_ref": "opaque-workspace-ref",
        "resource_refs": [RESOURCE],
        "scopes": ["agent.run", "trench.event.read"],
        "limits": {
            "max_runtime_seconds": 300,
            "max_model_tokens": 100_000,
            "max_artifact_bytes": 10_485_760,
        },
        "origin": "https://trench.example.com",
        "policy_version": "trench-policy-v1",
    }
    claims.update(overrides)
    return HostSessionGrant.model_validate(claims)


def test_valid_grant_derives_secret_free_context_and_enforces_scope() -> None:
    grant = make_grant()

    context = grant.validate_against(
        now=NOW,
        expected_issuer="https://api.trench.example.com/",
        expected_audience="zebra-embedded",
        expected_host_app_id="trench",
        allowed_origins=("https://trench.example.com/",),
    )

    assert context.grant_id == "grant_01"
    assert context.namespace_id == "opaque-namespace-ref"
    assert context.resource_refs == (HostResourceRef(type="trench.event", id="evt_123"),)
    context.require_scope("agent.run")
    context.require_resource(HostResourceRef(type="trench.event", id="evt_123"))
    with pytest.raises(HostGrantScopeError):
        context.require_scope("trench.event.write")
    with pytest.raises(HostGrantScopeError):
        context.require_resource(HostResourceRef(type="trench.event", id="evt_999"))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("expected_issuer", "https://other.example.com"),
        ("expected_audience", "other-audience"),
        ("expected_host_app_id", "other-host"),
        ("allowed_origins", ("https://other.example.com",)),
    ),
)
def test_trusted_binding_mismatches_fail_closed(field: str, value: object) -> None:
    grant = make_grant()
    kwargs: dict[str, object] = {
        "now": NOW,
        "expected_issuer": "https://api.trench.example.com",
        "expected_audience": "zebra-embedded",
        "expected_host_app_id": "trench",
        "allowed_origins": ("https://trench.example.com",),
    }
    kwargs[field] = value

    with pytest.raises(HostGrantMismatchError):
        grant.validate_against(**kwargs)  # type: ignore[arg-type]


def test_expired_and_not_yet_valid_grants_are_typed() -> None:
    expired = make_grant(exp=int(NOW.timestamp()))
    with pytest.raises(HostGrantExpiredError):
        expired.validate_against(
            now=NOW,
            expected_issuer="https://api.trench.example.com",
            expected_audience="zebra-embedded",
            allowed_origins=("https://trench.example.com",),
        )

    not_yet_valid = make_grant(iat=int(NOW.timestamp()) + 60, nbf=int(NOW.timestamp()) + 60)
    with pytest.raises(HostGrantNotYetValidError):
        not_yet_valid.validate_against(
            now=NOW,
            expected_issuer="https://api.trench.example.com",
            expected_audience="zebra-embedded",
            allowed_origins=("https://trench.example.com",),
        )


@pytest.mark.parametrize(
    "overrides",
    (
        {"scopes": []},
        {"scopes": ["agent.run", "agent.run"]},
        {"resource_refs": []},
        {"resource_refs": [RESOURCE, RESOURCE]},
        {"origin": "https://trench.example.com/path"},
        {"origin": "*"},
        {"limits": {"max_runtime_seconds": 0, "max_model_tokens": 1, "max_artifact_bytes": 1}},
        {"iat": 50, "nbf": 40, "exp": 100},
        {"token": "raw-jwt-must-not-be-a-claim"},
    ),
)
def test_malformed_claims_are_rejected_before_context_derivation(
    overrides: dict[str, object],
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        make_grant(**overrides)


def test_wildcard_origin_is_never_an_exact_allowlist() -> None:
    grant = make_grant()
    with pytest.raises(HostGrantMismatchError):
        grant.validate_against(
            now=NOW,
            expected_issuer="https://api.trench.example.com",
            expected_audience="zebra-embedded",
            allowed_origins=("*",),
        )
