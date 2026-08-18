from datetime import UTC, datetime

import jwt
import pytest
from agent_core.domain.host_authority import HostSessionGrant
from agent_security import (
    CachingJwksKeyResolver,
    HostGrantDecodeError,
    HostGrantVerificationConfig,
    JwtAlgorithm,
    PyJwtHostGrantDecoder,
)
from cryptography.hazmat.primitives.asymmetric import rsa


def _config() -> HostGrantVerificationConfig:
    return HostGrantVerificationConfig(
        issuer="https://api.trench.example.com",
        audience="zebra-embedded",
        jwks_uri="https://api.trench.example.com/.well-known/jwks.json",
        allowed_origins=("https://trench.example.com",),
    )


def _claims(**overrides: object) -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    values: dict[str, object] = {
        "iss": "https://api.trench.example.com",
        "aud": "zebra-embedded",
        "sub": "opaque-subject",
        "jti": "jti-1",
        "iat": now - 1,
        "nbf": now - 1,
        "exp": now + 300,
        "host_app_id": "trench",
        "namespace_id": "tenant-a",
        "workspace_ref": "workspace-a",
        "resource_refs": [{"type": "trench.event", "id": "evt-1"}],
        "scopes": ["agent.run", "trench.event.read"],
        "limits": {
            "max_runtime_seconds": 300,
            "max_model_tokens": 100_000,
            "max_artifact_bytes": 10_485_760,
        },
        "origin": "https://trench.example.com",
        "policy_version": "policy-v1",
    }
    values.update(overrides)
    return values


class _StaticResolver:
    def __init__(self, key: object) -> None:
        self.key = key

    def resolve(self, jwks_uri: str, token: str) -> object:
        assert jwks_uri.startswith("https://")
        assert token
        return self.key


def test_pyjwt_decoder_verifies_rs256_and_returns_core_claims_without_token() -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    token = jwt.encode(_claims(), private_key, algorithm="RS256")
    decoded = PyJwtHostGrantDecoder(_StaticResolver(private_key.public_key())).decode(
        token,
        config=_config(),
    )

    assert isinstance(decoded.grant, HostSessionGrant)
    assert decoded.algorithm is JwtAlgorithm.RS256
    assert "Bearer" not in repr(decoded)
    assert "token" not in decoded.grant.model_dump()


def test_pyjwt_decoder_rejects_forged_expired_and_wrong_algorithm_tokens() -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    resolver = _StaticResolver(private_key.public_key())
    decoder = PyJwtHostGrantDecoder(resolver)

    forged_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    forged = jwt.encode(_claims(scopes=["agent.admin"]), forged_key, algorithm="RS256")
    with pytest.raises(HostGrantDecodeError):
        decoder.decode(forged, config=_config())

    expired = jwt.encode(_claims(exp=1), private_key, algorithm="RS256")
    with pytest.raises(HostGrantDecodeError):
        decoder.decode(expired, config=_config())

    hs256 = jwt.encode(_claims(), "shared-secret-that-is-at-least-32-bytes", algorithm="HS256")
    with pytest.raises(HostGrantDecodeError):
        decoder.decode(hs256, config=_config())


def test_jwks_resolver_bounds_timeout_and_cache_lifespan() -> None:
    with pytest.raises(ValueError):
        CachingJwksKeyResolver(timeout_seconds=0)
    with pytest.raises(ValueError):
        CachingJwksKeyResolver(cache_lifespan_seconds=3_601)
