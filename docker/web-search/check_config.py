"""Offline check inside the pinned SearXNG image; no search or provider RPC."""

import logging
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import yaml
from searx.engines import yahoo as yahoo_engine
from searx.engines.zebra_exa import OPTIONAL_CONFIG
from searx.settings_loader import update_settings


def main() -> None:
    root = Path(__file__).resolve().parent
    source = yaml.safe_load((root / "settings.yml").read_text())
    defaults = yaml.safe_load(Path("/usr/local/searxng/searx/settings.yml").read_text())
    merged = update_settings(deepcopy(defaults), source)
    engines = merged["engines"]
    assert len({e["name"] for e in engines}) == len(engines)
    assert {e["name"] for e in engines if not e.get("disabled") and not e.get("inactive")} == {
        "yahoo"
    }
    assert next(e for e in engines if e["name"] == "exa") == OPTIONAL_CONFIG
    yahoo_config = next(e for e in engines if e["name"] == "yahoo")
    assert yahoo_config["retries"] == 1 and yahoo_config["retry_on_http_error"] == [0]
    search, server, outgoing = (merged[k] for k in ("search", "server", "outgoing"))
    assert "json" in search["formats"] and search["safe_search"] == 1
    assert search["default_lang"] == "all" and search["max_page"] == 1
    assert search["autocomplete"] == search["favicon_resolver"] == ""
    assert search["suspended_times"]["SearxEngineTooManyRequests"] >= 3600
    assert search["suspended_times"]["SearxEngineCaptcha"] >= 86400
    assert search["suspended_times"]["SearxEngineAccessDenied"] >= 86400
    assert not server["public_instance"] and not server["image_proxy"] and not server["limiter"]
    assert outgoing["request_timeout"] == 5 and outgoing["max_request_timeout"] == 6
    assert outgoing["pool_connections"] == 20 and outgoing["enable_http2"]
    # Verify the pinned Yahoo adapter actually stops forcing the Chinese cookie.
    yahoo_engine.CACHE = SimpleNamespace(get=lambda _: None)
    yahoo_engine.logger = logging.getLogger("offline.yahoo")
    for locale, language in (("all", "lang_any"), ("zh-CN", "lang_zh_chs")):
        params = {
            "searxng_locale": locale,
            "time_range": "",
            "pageno": 1,
            "safesearch": 1,
            "cookies": {},
        }
        yahoo_engine.request("offline configuration check", params)
        assert parse_qs(params["cookies"]["sB"])["vl"] == [language]
    # One source of truth: image fallback and both normal/compatibility mounts agree.
    for filename in ("compose.yml", "compose.exa.yml"):
        compose = yaml.safe_load((root / filename).read_text())
        assert compose["services"]["searxng"]["environment"]["SEARXNG_SETTINGS_PATH"] == (
            "/etc/searxng/settings.yml"
        )
    print(
        "PASS: merged settings, Yahoo default, optional Exa, bounded transport/cooldown; zero RPC"
    )


if __name__ == "__main__":
    main()
