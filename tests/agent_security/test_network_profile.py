import pytest
from agent_security import (
    DEFAULT_NETWORK_PROFILE,
    SUPPORTED_NETWORK_PROFILES,
    NetworkProfile,
    NetworkProfileError,
    NetworkProfileName,
    parse_network_profile,
)


def test_supported_network_profiles_match_architecture_contract() -> None:
    assert SUPPORTED_NETWORK_PROFILES == (
        "none",
        "setup-only",
        "domain-allowlist",
        "mcp-proxy-only",
        "git-proxy-only",
        "full-trusted-local",
    )


def test_default_network_profile_is_fail_closed() -> None:
    assert DEFAULT_NETWORK_PROFILE == NetworkProfile(name=NetworkProfileName.NONE)
    assert DEFAULT_NETWORK_PROFILE.is_fail_closed is True
    assert DEFAULT_NETWORK_PROFILE.domain_allowlist == ()


@pytest.mark.parametrize("profile_name", SUPPORTED_NETWORK_PROFILES)
def test_parse_network_profile_accepts_supported_names(profile_name: str) -> None:
    if profile_name == "domain-allowlist":
        profile = parse_network_profile(profile_name, domain_allowlist=("github.com",))
    else:
        profile = parse_network_profile(profile_name)

    assert profile.name.value == profile_name
    expected_allowlist = ("github.com",) if profile_name == "domain-allowlist" else ()
    assert profile.domain_allowlist == expected_allowlist


def test_domain_allowlist_profile_normalizes_domains() -> None:
    profile = parse_network_profile(
        "domain-allowlist",
        domain_allowlist=(" GitHub.com ", "api.github.com", "github.com"),
    )

    assert profile.name is NetworkProfileName.DOMAIN_ALLOWLIST
    assert profile.domain_allowlist == ("github.com", "api.github.com")
    assert profile.is_fail_closed is False


def test_domain_allowlist_profile_requires_domains() -> None:
    with pytest.raises(NetworkProfileError, match="requires at least one allowed domain"):
        parse_network_profile("domain-allowlist")


def test_non_allowlist_profile_rejects_domain_allowlist() -> None:
    with pytest.raises(NetworkProfileError, match="does not accept a domain allowlist"):
        parse_network_profile("setup-only", domain_allowlist=("github.com",))


def test_parse_network_profile_rejects_unknown_name() -> None:
    with pytest.raises(NetworkProfileError, match="unsupported network profile"):
        parse_network_profile("internet-open")


def test_parse_network_profile_rejects_blank_name() -> None:
    with pytest.raises(NetworkProfileError, match="must not be blank"):
        parse_network_profile(" ")


@pytest.mark.parametrize("domain", ("https://github.com", "github.com/path", "*.github.com"))
def test_domain_allowlist_rejects_ambiguous_domain_entries(domain: str) -> None:
    with pytest.raises(NetworkProfileError, match="bare hostnames"):
        parse_network_profile("domain-allowlist", domain_allowlist=(domain,))


def test_domain_allowlist_rejects_blank_entries() -> None:
    with pytest.raises(NetworkProfileError, match="must not be blank"):
        parse_network_profile("domain-allowlist", domain_allowlist=(" ",))


def test_domain_allowlist_rejects_non_string_entries() -> None:
    with pytest.raises(NetworkProfileError, match="must be strings"):
        parse_network_profile("domain-allowlist", domain_allowlist=("github.com", 1))  # type: ignore[arg-type]
