from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Mem0GatewayConfig:
    enabled: bool = False
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    allow_insecure_http: bool = False
    trust_environment_proxy: bool = False
    timeout_seconds: float = 5.0
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 30.0

    def __post_init__(self) -> None:
        base_url = self.base_url.strip().rstrip("/")
        api_key = self.api_key.strip()
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "api_key", api_key)

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.circuit_failure_threshold < 1:
            raise ValueError("circuit_failure_threshold must be positive")
        if self.circuit_recovery_seconds <= 0:
            raise ValueError("circuit_recovery_seconds must be positive")
        if not self.enabled:
            return
        if not base_url:
            raise ValueError("enabled Mem0 Gateway requires base_url")
        if not api_key:
            raise ValueError("enabled Mem0 Gateway requires api_key")

        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain credentials, query or fragment")
        if parsed.scheme == "http" and not self.allow_insecure_http:
            raise ValueError("HTTP base_url requires explicit allow_insecure_http")
