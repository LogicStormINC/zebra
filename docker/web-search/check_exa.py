"""Offline native assertions; run in the pinned image with --network none."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from curl_cffi.requests.exceptions import Timeout
from searx.engines import check_engine_module
from searx.search.processors.online import default_request_params
from searx.settings_loader import update_settings

path = Path(__file__).with_name("zebra_exa.py")
spec = importlib.util.spec_from_file_location("zebra_exa_check", path)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def response(result=None, *, status=200, headers=None, raw=None, identity=2):
    text = (
        raw
        if raw is not None
        else json.dumps({"jsonrpc": "2.0", "id": identity, "result": result or {}})
    )
    return SimpleNamespace(
        status_code=status, headers=headers or {}, text=text, content=text.encode()
    )


def sources(text="rate limit and quota documentation"):
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "results": [
                            {"url": "https://example.com/page", "title": "Title", "text": text}
                        ]
                    }
                ),
            }
        ]
    }


def params():
    engine._network.set_timeout_for_thread(6, start_time=time.monotonic())
    return dict(
        default_request_params(), pageno=1, time_range="", searxng_locale="zh-CN", safesearch=1
    )


def rejected(call, exception):
    try:
        call()
    except exception:
        return
    raise AssertionError("expected rejection")


def main():
    check_engine_module(engine)
    settings = yaml.safe_load(Path(__file__).with_name("settings.yml").read_text())
    defaults = yaml.safe_load(Path("/usr/local/searxng/searx/settings.yml").read_text())
    optional = deepcopy(settings)
    optional["engines"].insert(0, engine.OPTIONAL_CONFIG)
    for config in (settings, optional):
        merged = update_settings(deepcopy(defaults), config)
        assert {
            e["name"] for e in merged["engines"] if not e.get("disabled") and not e.get("inactive")
        } == {"yahoo"}
    with tempfile.TemporaryDirectory() as directory:
        engine.STATE = Path(directory) / "state.json"
        assert len(engine._results(response(sources()))) == 1
        for r in (
            response(raw="", status=429),
            response({"isError": True, "content": [{"text": "Too many requests"}]}),
            response(
                {
                    "content": [
                        {"text": "You've hit Exa's free MCP rate limit. Create your own API key."}
                    ]
                }
            ),
        ):
            rejected(lambda r=r: engine._results(r), engine.RateLimit)
        rejected(
            lambda: engine._message(
                SimpleNamespace(
                    status_code=200,
                    content=b"x",
                    text=json.dumps({"id": 2, "error": {"code": 429}}),
                ),
                2,
            ),
            engine.RateLimit,
        )
        for r in (
            response(raw="not JSON"),
            response({"content": []}),
            response({"content": [{"text": "ordinary provider error"}]}),
            response(sources(), identity=99),
            response(raw="x" * 262145),
        ):
            rejected(lambda r=r: engine._results(r), ValueError)
        sse = "event: message\ndata: " + response(sources()).text + "\n\n"
        assert len(engine._results(response(raw=sse))) == 1
        lease = engine._reserve()
        assert lease and not engine._reserve()
        engine._finish(lease, "rate_limit")
        until = json.loads(engine.STATE.read_text())["until"]
        assert 899 <= until - time.time() <= 901
        assert not engine._reserve()
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib.util,sys;from pathlib import Path;"
                "s=importlib.util.spec_from_file_location('other',sys.argv[1]);"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                "m.STATE=Path(sys.argv[2]);assert not m._reserve()",
                str(path),
                str(engine.STATE),
            ],
            capture_output=True,
        )
        assert child.returncode == 0, "cooldown not shared across processes"
        engine._finish(lease, "rate_limit", "1200")
        assert json.loads(engine.STATE.read_text())["until"] >= time.time() + 1199
        engine._finish(lease, "rate_limit", "999999")
        assert json.loads(engine.STATE.read_text())["blocked"] is True
        engine.STATE.write_text('{"until":0,"lease":0,"blocked":true}')
        assert not engine._reserve(), "over-cap Retry-After must not auto-recover"
        engine.STATE.write_text('{"until":0,"lease":0}')
        with ThreadPoolExecutor(max_workers=8) as pool:
            attempts = list(pool.map(lambda _: engine._reserve(), range(8)))
        assert sum(bool(a) for a in attempts) == 1, "concurrent probes amplified anonymous traffic"
        owner = json.loads(engine.STATE.read_text())["owner"]
        engine._finish("stale-owner")
        assert json.loads(engine.STATE.read_text())["lease"] > time.time()
        engine._finish(owner)
        engine.STATE.write_text("corrupt")
        assert not engine._reserve(), "corrupt state must fail closed"

        calls = []

        def yahoo_request(query, data):
            calls.append(("yahoo", query))
            data["url"] = "https://search.yahoo.com/search"
            data["cookies"] = {}

        yahoo = SimpleNamespace(request=yahoo_request, response=lambda r: ["yahoo-result"])
        with (
            patch.dict(engine.engines, {"yahoo": yahoo}),
            patch.object(engine._network, "set_context_network_name"),
            patch.object(engine._network, "get") as get,
            patch.object(engine._network, "post") as post,
        ):
            engine.STATE.write_text('{"until":9999999999,"lease":0}')
            data = params()
            engine.request("same exact query", data)
            assert calls == [("yahoo", "same exact query")] and not post.called
            assert data["method"] == "GET" and data["json"] == {}
            engine.STATE.write_text("{}")
            provider_headers = {
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
                "Mcp-Session-Id": "offline-session",
            }
            engine._session = provider_headers.copy()
            data = params()
            engine.request("same exact query", data)
            assert data["json"]["params"]["arguments"]["query"] == "same exact query"
            r = response({"content": [{"text": "Exa free MCP rate limit"}]})
            r.search_params = data
            get.return_value = SimpleNamespace()
            assert engine.response(r) == ["yahoo-result"]
            assert get.call_count == 1 and not post.called
            until = json.loads(engine.STATE.read_text())["until"]
            assert until > time.time()
            assert engine._session == provider_headers, "rate limit discarded initialized session"
            calls.clear()
            for _ in range(3):
                engine.request("new query", params())
            assert len(calls) == 3 and not post.called, "cooldown contacted Exa"
            assert engine._session == provider_headers
            # Only a private, network-disabled test clock advances; real quota state is untouched.
            with patch.object(engine.time, "time", return_value=until + 1):
                recovered = params()
                engine.request("after cooldown", recovered)
            assert recovered["headers"] == provider_headers and not post.called, (
                "recovery reinitialized MCP"
            )
            assert recovered["json"]["method"] == "tools/call"
            r = response(status=404)
            r.search_params = recovered
            assert engine.response(r) == ["yahoo-result"]
            assert engine._session is None, "invalid session was reused"
            engine.STATE.write_text("{}")
            engine._session = {"Accept": "application/json"}
            data = params()
            engine.request("safe", data)
            r = response(sources())
            r.search_params = data
            assert len(engine.response(r)) == 1
            assert json.loads(engine.STATE.read_text())["lease"] == 0
            engine.STATE.write_text("{}")
            engine._session = None
            post.side_effect = [
                response({"protocolVersion": "2025-03-26"}, identity=1),
                response(status=202),
            ]
            data = params()
            engine.request("cold", data)
            assert post.call_count == 2 and data["json"]["method"] == "tools/call"
            for limited_step in ("initialize", "notification"):
                engine.STATE.write_text("{}")
                engine._session = None
                calls.clear()
                limit = response(status=429, headers={"retry-after": "1200"})
                post.side_effect = (
                    [limit]
                    if limited_step == "initialize"
                    else [response({"protocolVersion": "2025-03-26"}, identity=1), limit]
                )
                engine.request("limited setup", params())
                assert calls == [("yahoo", "limited setup")]
                assert json.loads(engine.STATE.read_text())["until"] >= time.time() + 1199
            engine.STATE.write_text("{}")
            engine._session = None
            post.side_effect = Timeout("cancelled")
            calls.clear()
            rejected(lambda: engine.request("cancelled", params()), Timeout)
            assert not calls, "timeout started Yahoo fallback"
            engine.STATE.write_text('{"until":9999999999}')
            threading.current_thread()._timeout = True
            try:
                rejected(lambda: engine.request("stopped", params()), Timeout)
                assert not calls, "stopped request started Yahoo fallback"
                engine.STATE.write_text("{}")
                previous = post.call_count
                rejected(lambda: engine.request("stopped", params()), Timeout)
                assert post.call_count == previous, "stopped request contacted Exa"
            finally:
                del threading.current_thread()._timeout
            data = params()
            data["_exa_original"] = (0.01, time.monotonic() - 1)
            rejected(lambda: engine._yahoo("late", data), Timeout)
    print("PASS: limits, persistent cooldown/lease, Yahoo fallback and stop/deadline; no network")


if __name__ == "__main__":
    main()
