"""Environment-driven configuration for the Host Grant broker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_ALLOWED_SCOPES = (
    "agent.run",
    "event.read",
    "evidence.read",
    "entity.read",
    "topic.read",
    "source.read",
    "history.read",
    "artifact.read",
    "artifact.publish",
    "subscription.write",
)


class BrokerConfigError(ValueError):
    """Raised when broker configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class BrokerSettings:
    issuer: str
    audience: str
    host_app_id: str
    namespace_id: str
    workspace_ref: str
    origin: str
    policy_version: str
    allowed_scopes: tuple[str, ...]
    private_key_pem: str
    key_id: str
    ttl_seconds: int
    trench_me_url: str
    trench_sources_url: str
    trench_timeout_seconds: float
    max_runtime_seconds: int
    max_model_tokens: int
    max_artifact_bytes: int
    workload_identities: tuple[str, ...] = ()
    workload_shared_secret: str = ""
    workload_clock_skew_seconds: int = 60

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> BrokerSettings:
        source = dict(os.environ if env is None else env)
        prefix = "ZEBRA_GRANT_BROKER_"
        issuer = _https_origin(_require(source, f"{prefix}ISSUER"), "ISSUER")
        origin = _https_origin(_require(source, f"{prefix}ORIGIN"), "ORIGIN")
        private_key_pem = _private_key(source, prefix)
        return cls(
            issuer=issuer,
            audience=_text(source.get(f"{prefix}AUDIENCE", "zebra"), "AUDIENCE", 512),
            host_app_id=_text(source.get(f"{prefix}HOST_APP_ID", "trench"), "HOST_APP_ID", 128),
            namespace_id=_text(source.get(f"{prefix}NAMESPACE_ID", "trench"), "NAMESPACE_ID", 512),
            workspace_ref=_text(
                source.get(f"{prefix}WORKSPACE_REF", "trench"), "WORKSPACE_REF", 512
            ),
            origin=origin,
            policy_version=_text(
                source.get(f"{prefix}POLICY_VERSION", "trench-read-v1"),
                "POLICY_VERSION",
                128,
            ),
            allowed_scopes=_scopes(source.get(f"{prefix}ALLOWED_SCOPES")),
            private_key_pem=private_key_pem,
            key_id=_text(
                source.get(f"{prefix}KEY_ID", "trench-host-grant-v1"), "KEY_ID", 128
            ),
            ttl_seconds=_bounded_int(
                source.get(f"{prefix}TTL_SECONDS", "1900"), "TTL_SECONDS", 1, 3600
            ),
            trench_me_url=_https_url(_require(source, f"{prefix}TRENCH_ME_URL"), "TRENCH_ME_URL"),
            trench_sources_url=_https_url(
                _require(source, f"{prefix}TRENCH_SOURCES_URL"),
                "TRENCH_SOURCES_URL",
            ),
            trench_timeout_seconds=float(
                _bounded_int(
                    source.get(f"{prefix}TRENCH_TIMEOUT_SECONDS", "5"),
                    "TRENCH_TIMEOUT_SECONDS",
                    1,
                    30,
                )
            ),
            max_runtime_seconds=_bounded_int(
                source.get(f"{prefix}MAX_RUNTIME_SECONDS", "1800"),
                "MAX_RUNTIME_SECONDS",
                1,
                86_400,
            ),
            max_model_tokens=_bounded_int(
                source.get(f"{prefix}MAX_MODEL_TOKENS", "1000000"),
                "MAX_MODEL_TOKENS",
                1,
                10_000_000,
            ),
            max_artifact_bytes=_bounded_int(
                source.get(f"{prefix}MAX_ARTIFACT_BYTES", "64000000"),
                "MAX_ARTIFACT_BYTES",
                1,
                1_073_741_824,
            ),
            workload_identities=_scopes(source.get(f"{prefix}WORKLOAD_IDENTITIES"))
            if source.get(f"{prefix}WORKLOAD_IDENTITIES", "").strip()
            else (),
            workload_shared_secret=source.get(f"{prefix}WORKLOAD_SHARED_SECRET", "").strip(),
            workload_clock_skew_seconds=_bounded_int(
                source.get(f"{prefix}WORKLOAD_CLOCK_SKEW_SECONDS", "60"),
                "WORKLOAD_CLOCK_SKEW_SECONDS",
                1,
                300,
            ),
        )


def _require(source: dict[str, str], name: str) -> str:
    value = source.get(name, "").strip()
    if not value:
        raise BrokerConfigError(f"{name} is required")
    return value


def _text(value: str, name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise BrokerConfigError(f"{name} must be non-blank and at most {maximum} characters")
    return normalized


def _bounded_int(value: str, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise BrokerConfigError(f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise BrokerConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _scopes(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_ALLOWED_SCOPES
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not values or len(set(values)) != len(values) or len(values) > 64:
        raise BrokerConfigError("ALLOWED_SCOPES must be 1-64 unique comma-separated values")
    return values


def _private_key(source: dict[str, str], prefix: str) -> str:
    inline = source.get(f"{prefix}PRIVATE_KEY_PEM", "").strip()
    if inline:
        return inline.replace("\\n", "\n")
    path = source.get(f"{prefix}PRIVATE_KEY_FILE", "").strip()
    if not path:
        raise BrokerConfigError(
            f"one of {prefix}PRIVATE_KEY_PEM or {prefix}PRIVATE_KEY_FILE is required"
        )
    try:
        with open(path) as handle:
            return handle.read()
    except OSError as exc:
        raise BrokerConfigError(f"PRIVATE_KEY_FILE could not be read: {path}") from exc


def _https_origin(value: str, name: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        raise BrokerConfigError(f"{name} must be an HTTPS origin without a path")
    host = parsed.hostname
    if host is None:
        raise BrokerConfigError(f"{name} must contain a host")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"https://{host.lower()}{port}"


def _https_url(value: str, name: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise BrokerConfigError(f"{name} must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise BrokerConfigError(f"{name} must not contain credentials")
    return value
