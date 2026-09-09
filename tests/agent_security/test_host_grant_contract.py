from datetime import UTC, datetime

import jwt
import pytest
from agent_core.domain.host_authority import HostResourceRef, HostSessionGrant
from agent_security.host_grant import (
    HostGrantAlgorithmError,
    HostGrantBindingError,
    HostGrantVerificationConfig,
    HostGrantVerifier,
    JwtAlgorithm,
)
from agent_security.jwt_adapter import PyJwtHostGrantDecoder
from cryptography.hazmat.primitives.asymmetric import rsa

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
RESOURCE = HostResourceRef(type="trench.event", id="evt_123")


def _grant(**overrides: object) -> HostSessionGrant:
    claims: dict[str, object] = {
        "iss": "https://api.trench.example.com",
        "aud": "zebra-embedded",
        "sub": "opaque-subject",
        "jti": "grant_01",
        "iat": int(NOW.timestamp()) - 10,
        "nbf": int(NOW.timestamp()) - 10,
        "exp": int(NOW.timestamp()) + 300,
        "host_app_id": "trench",
        "namespace_id": "opaque-namespace",
        "workspace_ref": "opaque-workspace",
        "resource_refs": [RESOURCE.model_dump(by_alias=True)],
        "scopes": ["agent.run", "trench.event.read"],
        "limits": {
            "max_runtime_seconds": 300,
            "max_model_tokens": 100_000,
            "max_artifact_bytes": 10_485_760,
        },
        "origin": "https://trench.example.com",
        "policy_version": "policy-v1",
    }
    claims.update(overrides)
    return HostSessionGrant.model_validate(claims)


def _verifier(**overrides: object) -> HostGrantVerifier:
    values: dict[str, object] = {
        "issuer": "https://api.trench.example.com/",
        "audience": "zebra-embedded",
        "jwks_uri": "https://api.trench.example.com/.well-known/jwks.json",
        "allowed_origins": ("https://trench.example.com/",),
    }
    values.update(overrides)
    return HostGrantVerifier(HostGrantVerificationConfig(**values))


def test_verifier_returns_secret_free_bound_context() -> None:
    verified = _verifier().verify(
        _grant(),
        algorithm=JwtAlgorithm.RS256,
        now=NOW,
        expected_host_app_id="trench",
        required_scopes=("trench.event.read",),
        required_resources=(RESOURCE,),
    )

    assert verified.grant_id == "grant_01"
    assert verified.context.namespace_id == "opaque-namespace"
    assert verified.algorithm is JwtAlgorithm.RS256
    assert verified.authority_issuer == "https://api.trench.example.com"
    assert verified.subject_ref == "opaque-subject"
    assert "token" not in verified.context.model_dump()


def test_signed_grant_preserves_identity_without_changing_context() -> None:
    now = datetime.now(UTC)
    grant = _grant(
        iat=int(now.timestamp()) - 1,
        nbf=int(now.timestamp()) - 1,
        exp=int(now.timestamp()) + 300,
    )
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)

    class KeyResolver:
        def resolve(self, jwks_uri: str, token: str) -> object:
            return private_key.public_key()

    verifier = _verifier()
    token = jwt.encode(grant.model_dump(by_alias=True), private_key, algorithm="RS256")
    decoded = PyJwtHostGrantDecoder(KeyResolver()).decode(token, config=verifier.config)
    verified = verifier.verify(decoded.grant, algorithm=decoded.algorithm, now=now)
    expected = grant.validate_against(
        now=now,
        expected_issuer=verifier.config.issuer,
        expected_audience=verifier.config.audience,
        allowed_origins=verifier.config.allowed_origins,
    )

    assert verified.authority_issuer == grant.iss
    assert verified.subject_ref == grant.sub
    assert verified.context.model_dump_json() == expected.model_dump_json()
    assert hash(verified.context) == hash(expected)
    assert "authority_issuer" not in verified.context.model_dump()
    assert "subject_ref" not in verified.context.model_dump()


def test_algorithm_and_binding_fail_closed() -> None:
    with pytest.raises(HostGrantAlgorithmError):
        _verifier().verify(_grant(), algorithm=JwtAlgorithm.ES256, now=NOW)
    with pytest.raises(HostGrantBindingError):
        _verifier().verify(
            _grant(),
            algorithm=JwtAlgorithm.RS256,
            now=NOW,
            required_scopes=("trench.event.write",),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("algorithms", frozenset()),
        ("algorithms", frozenset({"HS256"})),
        ("allowed_origins", ("*",)),
        ("allowed_origins", ("http://trench.example.com",)),
        ("jwks_uri", "http://api.trench.example.com/jwks"),
        ("clock_skew_seconds", 301),
    ),
)
def test_verification_config_rejects_unsafe_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "issuer": "https://api.trench.example.com",
        "audience": "zebra-embedded",
        "jwks_uri": "https://api.trench.example.com/jwks",
        "allowed_origins": ("https://trench.example.com",),
    }
    values[field] = value
    with pytest.raises(ValueError):
        HostGrantVerificationConfig(**values)
