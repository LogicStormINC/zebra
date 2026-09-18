"""Production Host Grant composition for the API boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import logging

from agent_core.domain.host_authority import HostSessionGrant
from agent_security import (
    CachingJwksKeyResolver,
    HostGrantBindingError,
    HostGrantSecurityError,
    HostGrantVerificationConfig,
    HostGrantVerifier,
    JwtAlgorithm,
    PyJwtHostGrantDecoder,
)
from agent_storage import HostGrantAttempt, HostRegistryRecord, PostgresHostAuthorityStore

from zebra_agent_api.http import HostGrantHttpRequest, HostGrantRequestAuthorizer

_DEFAULT_REQUIRED_SCOPES = ("agent.run",)
logger = logging.getLogger(__name__)


def build_postgres_host_grant_authorizer(
    database_url: str,
    *,
    deployment_namespace: str,
) -> PostgresHostGrantRequestAuthorizer:
    """Compose the production Host Grant adapter over the cloud authority store."""
    return PostgresHostGrantRequestAuthorizer(
        registry=PostgresHostAuthorityStore(
            database_url,
            deployment_namespace=deployment_namespace,
        ),
        decoder=PyJwtHostGrantDecoder(CachingJwksKeyResolver()),
    )


@dataclass(frozen=True)
class PostgresHostGrantRequestAuthorizer(HostGrantRequestAuthorizer):
    """Verify signed Grants and atomically consume their jti in PostgreSQL."""

    registry: PostgresHostAuthorityStore
    decoder: PyJwtHostGrantDecoder
    required_scopes: tuple[str, ...] = _DEFAULT_REQUIRED_SCOPES
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), repr=False)

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        origins = {
            origin
            for record in self.registry.list_registries()
            for origin in record.allowed_origins
        }
        return tuple(sorted(origins))

    def authorize(self, request: HostGrantHttpRequest) -> object:
        token = _bearer_token(request.authorization)
        for record in self.registry.list_registries():
            config = _verification_config(record)
            try:
                decoded = self.decoder.decode(token, config=config)
            except HostGrantSecurityError as exc:
                logger.warning("Host Grant decode rejected: %s: %s", type(exc).__name__, str(exc))
                continue
            attempt = _attempt_for(
                token,
                decoded.grant,
                algorithm=decoded.algorithm,
            )
            verifier = HostGrantVerifier(config)
            try:
                required_scopes = _required_scopes_for_request(request)
                verified = verifier.verify(
                    decoded.grant,
                    algorithm=decoded.algorithm,
                    now=self.now(),
                    expected_host_app_id=record.host_app_id,
                    required_scopes=required_scopes or self.required_scopes,
                )
                _require_request_origin(request.origin, verified.context.origin)
            except (HostGrantSecurityError, ValueError) as exc:
                logger.warning("Host Grant verifier detail: %s", type(exc).__name__)
                self.registry.record_rejection(attempt, "Host Grant binding or scope rejected")
                raise HostGrantBindingError("Host Grant binding or scope rejected") from exc
            decision = self.registry.consume_grant(attempt)
            if not decision.accepted:
                raise HostGrantBindingError("Host Grant replay rejected")
            return verified
        raise HostGrantBindingError("Host Grant signature or registry binding rejected")


def _required_scopes_for_request(request: HostGrantHttpRequest) -> tuple[str, ...]:
    if request.path == "/schedules" or request.path.startswith("/schedules/"):
        return (
            ("schedule.read",)
            if request.method in {"GET", "HEAD"}
            else ("agent.run", "schedule.manage")
        )
    if request.path.startswith("/v1/extensions/"):
        return (
            ("extensions.read",)
            if request.method in {"GET", "HEAD"}
            else ("extensions.manage",)
        )
    return ()


def _verification_config(record: HostRegistryRecord) -> HostGrantVerificationConfig:
    return HostGrantVerificationConfig(
        issuer=record.issuer,
        audience=record.audience,
        jwks_uri=record.jwks_uri,
        allowed_origins=record.allowed_origins,
        algorithms=frozenset(JwtAlgorithm(value) for value in record.algorithms),
    )


def _bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HostGrantBindingError("Host Grant bearer header is invalid")
    token = authorization.removeprefix(prefix).strip()
    if not token:
        raise HostGrantBindingError("Host Grant bearer header is empty")
    return token


def _attempt_for(
    token: str, grant: HostSessionGrant, *, algorithm: JwtAlgorithm
) -> HostGrantAttempt:
    return HostGrantAttempt(
        issuer=grant.iss,
        jti=grant.jti,
        host_app_id=grant.host_app_id,
        namespace_id=grant.namespace_id,
        algorithm=algorithm.value,
        grant_digest=sha256(token.encode()).hexdigest(),
        scopes_digest=_digest_text(grant.scopes),
        resource_digest=_digest_text(
            f"{resource.resource_type}:{resource.resource_id}"
            for resource in sorted(grant.resource_refs, key=lambda value: value.key)
        ),
        expires_at=datetime.fromtimestamp(grant.exp, UTC),
    )


def _digest_text(values: Iterable[str]) -> str:
    return sha256("\x1f".join(sorted(values)).encode()).hexdigest()


def _require_request_origin(request_origin: str | None, grant_origin: str) -> None:
    if request_origin is not None and request_origin.rstrip("/") != grant_origin.rstrip("/"):
        raise HostGrantBindingError("request origin does not match Host Grant")
