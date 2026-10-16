"""Run inside the pinned SearXNG interpreter, with optional settings path; no network."""

import asyncio
import json
import sys
from pathlib import Path

import yaml
from searx.engines.yahoo import response as yahoo_response
from searx.extended_types import SXNG_Response
from searx.network.network import Network

settings = yaml.safe_load(
    Path(sys.argv[1] if len(sys.argv) > 1 else "/etc/searxng/settings.yml").read_text()
)
engine = next(x for x in settings["engines"] if x["name"] == "yahoo")


async def check(statuses):
    seen = []
    closed = []

    class Client:
        async def request(self, method, url, **kw):
            status = statuses[min(len(seen), len(statuses) - 1)]
            seen.append(status)
            r = SXNG_Response()
            r.status_code = 403 if status == "captcha" else status
            r.ok = 200 <= r.status_code < 400
            if status == "captcha":
                r.headers["Server"] = "cloudflare"
                r.content = b"__cf_chl_captcha_tk__="
            r.reason = "OK"
            r.url = url
            r.search_params = {"cookies": {}, "headers": {}}
            return r

        async def aclose(self):
            closed.append(True)

    class TestedNetwork(Network):
        async def get_client(self, **_):
            return Client()

    n = TestedNetwork(
        retries=engine.get("retries", 0),
        retry_on_http_error=engine.get("retry_on_http_error", False),
    )
    try:
        r = await n.call_client(False, "GET", "https://search.yahoo.com/search")
        if r.status_code == 0:
            yahoo_response(r)  # Persistent invalid responses still fail in the real parser.
        result = r.status_code
    except Exception as e:
        result = type(e).__name__
    return seen, closed, result


async def main():
    outcomes = {}
    for statuses, expected in (
        ([0, 200], ([0, 200], 1, 200)),
        ([200], ([200], 0, 200)),
        ([0, 0], ([0, 0], 1, "HTTPError")),
        ([403, 200], ([403], 0, "SearxEngineAccessDeniedException")),
        ([429, 200], ([429], 0, "SearxEngineTooManyRequestsException")),
        (["captcha", 200], (["captcha"], 0, "SearxEngineCaptchaException")),
    ):
        seen, closed, result = await check(statuses)
        outcomes[str(statuses)] = dict(seen=seen, closed=len(closed), result=result)
        assert (seen, len(closed), result) == expected, outcomes
    print(json.dumps(outcomes, indent=2))


asyncio.run(main())
