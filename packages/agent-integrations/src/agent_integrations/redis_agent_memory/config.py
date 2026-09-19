from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class RedisAgentMemoryConfig:
    """Connection settings for the supported Redis Agent Memory data plane."""

    enabled: bool = False
    base_url: str = ""
    store_id: str = ""
    api_key: str = field(default="", repr=False)
    allow_insecure_http: bool = False
    trust_environment_proxy: bool = False
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        base_url = self.base_url.strip().rstrip("/")
        store_id = self.store_id.strip()
        api_key = self.api_key.strip()
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "store_id", store_id)
        object.__setattr__(self, "api_key", api_key)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not self.enabled:
            return
        if not base_url or not store_id or not api_key:
            raise ValueError("enabled Redis Agent Memory requires endpoint, store_id and api_key")
        if len(store_id) > 256:
            raise ValueError("store_id must not exceed 256 characters")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain credentials, query or fragment")
        if parsed.scheme == "http" and not self.allow_insecure_http:
            raise ValueError("HTTP base_url requires explicit allow_insecure_http")
