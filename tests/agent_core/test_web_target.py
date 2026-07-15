import pytest
from agent_core.domain.web import WebTargetError, parse_web_target


def test_parse_web_target_normalizes_public_https_url() -> None:
    target = parse_web_target(" HTTPS://Docs.Example.com/guide?q=agent ")

    assert target.hostname == "docs.example.com"
    assert target.url == "https://docs.example.com/guide?q=agent"


@pytest.mark.parametrize(
    "url",
    (
        "http://docs.example.com",
        "https://user@docs.example.com",
        "https://docs.example.com:443",
        "https://docs.example.com/page#section",
        "https://localhost/page",
        "https://127.0.0.1/page",
        "https://[::1]/page",
        "https://bad_host.example/page",
        "https://docs.example.com/bad path",
    ),
)
def test_parse_web_target_rejects_unsafe_url_shapes(url: str) -> None:
    with pytest.raises(WebTargetError):
        parse_web_target(url)
