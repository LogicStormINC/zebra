from pathlib import Path

from zebra_agent_config import load_settings


def test_private_search_is_operator_opt_in():
    assert load_settings(env={}).web_search_private_backend is False
    settings = load_settings(
        env={
            "ZEBRA_WEB_SEARCH_ENDPOINT": "https://search.zebra.test/search",
            "ZEBRA_WEB_SEARCH_PRIVATE_BACKEND": "true",
        }
    )
    assert settings.web_search_endpoint == "https://search.zebra.test/search"
    assert settings.web_search_private_backend is True


def test_compose_forwards_search_settings_without_opening_public_fetch():
    root = Path(__file__).resolve().parents[2]
    base = (root / "docker/compose.application.yml").read_text()
    assert "ZEBRA_WEB_SEARCH_ENDPOINT: ${ZEBRA_WEB_SEARCH_ENDPOINT:-}" in base
    assert "ZEBRA_WEB_SEARCH_PRIVATE_BACKEND: ${ZEBRA_WEB_SEARCH_PRIVATE_BACKEND:-false}" in base
    overlay = (root / "docker/compose.web-search.yml").read_text()
    assert "ZEBRA_WEB_SEARCH_ENDPOINT: https://search.zebra.test/search" in overlay
    assert 'ZEBRA_WEB_SEARCH_PRIVATE_BACKEND: "true"' in overlay
    assert "ZEBRA_DEVELOPMENT_UNRESTRICTED" not in overlay
