from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class NetworkProfileName(StrEnum):
    NONE = "none"
    SETUP_ONLY = "setup-only"
    DOMAIN_ALLOWLIST = "domain-allowlist"
    MCP_PROXY_ONLY = "mcp-proxy-only"
    GIT_PROXY_ONLY = "git-proxy-only"
    FULL_TRUSTED_LOCAL = "full-trusted-local"


class NetworkProfileError(ValueError):
    """Raised when a network profile configuration is invalid."""


def _normalize_profile_name(value: str | NetworkProfileName) -> NetworkProfileName:
    if isinstance(value, NetworkProfileName):
        return value
    normalized = value.strip()
    if not normalized:
        raise NetworkProfileError("network profile name must not be blank")
    try:
        return NetworkProfileName(normalized)
    except ValueError as exc:
        supported = ", ".join(SUPPORTED_NETWORK_PROFILES)
        raise NetworkProfileError(
            f"unsupported network profile {normalized!r}; expected one of: {supported}"
        ) from exc


def _normalize_domain_allowlist(value: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, str):
            raise NetworkProfileError("domain allowlist entries must be strings")
        candidate = entry.strip().lower()
        if not candidate:
            raise NetworkProfileError("domain allowlist entries must not be blank")
        if any(marker in candidate for marker in ("://", "/", "*", " ")):
            raise NetworkProfileError(
                "domain allowlist entries must be bare hostnames without paths or wildcards"
            )
        if candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    return tuple(normalized)


SUPPORTED_NETWORK_PROFILES = tuple(profile.value for profile in NetworkProfileName)


@dataclass(frozen=True)
class NetworkProfile:
    name: NetworkProfileName
    domain_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_name = _normalize_profile_name(self.name)
        normalized_allowlist = _normalize_domain_allowlist(self.domain_allowlist)
        if (
            normalized_name is NetworkProfileName.DOMAIN_ALLOWLIST
            and not normalized_allowlist
        ):
            raise NetworkProfileError(
                "domain-allowlist network profile requires at least one allowed domain"
            )
        if (
            normalized_name is not NetworkProfileName.DOMAIN_ALLOWLIST
            and normalized_allowlist
        ):
            raise NetworkProfileError(
                f"{normalized_name.value} network profile does not accept a domain allowlist"
            )
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "domain_allowlist", normalized_allowlist)

    @property
    def is_fail_closed(self) -> bool:
        return self.name is NetworkProfileName.NONE


DEFAULT_NETWORK_PROFILE = NetworkProfile(name=NetworkProfileName.NONE)


def parse_network_profile(
    value: str,
    *,
    domain_allowlist: Sequence[str] | None = None,
) -> NetworkProfile:
    return NetworkProfile(
        name=_normalize_profile_name(value),
        domain_allowlist=tuple(domain_allowlist or ()),
    )
