"""Run inside the pinned SearXNG image with --network none; no real credential needed."""

from __future__ import annotations

import stat
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

import yaml
from prepare_brave import render_settings, write_settings
from searx.engines import braveapi
from searx.settings_loader import update_settings


def main() -> None:
    source = Path(__file__).with_name("settings.yml").read_text()
    key = 'offline-only-"quoted\\token'
    base = yaml.safe_load(source)
    optional = yaml.safe_load(render_settings(source, key))
    brave = optional["engines"].pop(0)
    assert optional == base, "optional settings must otherwise preserve the exact base"
    assert brave["disabled"] is True and brave["inactive"] is False
    assert brave["shortcut"] == "brapi" and brave["api_key"] == key
    optional["engines"].insert(0, brave)
    defaults = yaml.safe_load(Path("/usr/local/searxng/searx/settings.yml").read_text())
    for settings in (base, optional):
        merged = update_settings(deepcopy(defaults), deepcopy(settings))
        enabled = {
            engine["name"]
            for engine in merged["engines"]
            if not engine.get("disabled", False) and not engine.get("inactive", False)
        }
        assert enabled == {"yahoo"}, enabled
    for invalid in ("", "a\nb", "a b", "密钥", "x" * 4097):
        try:
            render_settings(source, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid credential accepted")
    try:
        render_settings(source.replace("\nengines:\n", "\nrenamed:\n"), key)
    except ValueError:
        pass
    else:
        raise AssertionError("base layout drift accepted")
    with TemporaryDirectory() as directory:
        output = Path(directory) / "private/settings.yml"
        write_settings(output, render_settings(source, key))
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
        original = output.read_bytes()
        try:
            write_settings(output, "overwrite")
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing secret overwritten")
        assert output.read_bytes() == original
        link = output.with_name("link.yml")
        link.symlink_to(output)
        try:
            write_settings(link, "overwrite")
        except FileExistsError:
            pass
        else:
            raise AssertionError("secret symlink followed")
        assert output.read_bytes() == original
    braveapi.api_key = key
    braveapi.setup({})
    params = {"pageno": 1, "time_range": "", "safesearch": 1, "headers": {}}
    query = "Redis 8 正式发布日期 site:redis.io"
    braveapi.request(query, params)
    target = urlsplit(params["url"])
    assert target.scheme == "https" and target.hostname == "api.search.brave.com"
    assert target.path == "/res/v1/web/search"
    assert parse_qs(target.query)["q"] == [query]
    assert key not in params["url"] and params["headers"]["X-Subscription-Token"] == key
    print("PASS: Yahoo-only default, native Brave request, private files; no network")


if __name__ == "__main__":
    main()
