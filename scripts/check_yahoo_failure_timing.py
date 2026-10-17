"""Run inside SearXNG Python; verify error timing/privacy with no network."""

import asyncio
import logging

from curl_cffi import CurlInfo
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import Timeout
from searx.extended_types import SXNG_Response
from searx.network.client import AsyncClient

messages = []


class Capture(logging.Handler):
    def emit(self, record):
        messages.append(record.getMessage())


async def main():
    original = AsyncSession.request
    logger = logging.getLogger("searx.network.client")
    capture = Capture()
    logger.addHandler(capture)
    response = SXNG_Response()
    response.status_code = 0
    response.infos = {
        CurlInfo.NAMELOOKUP_TIME: 0.001,
        CurlInfo.CONNECT_TIME: 0.002,
        CurlInfo.APPCONNECT_TIME: 0.4,
        CurlInfo.PRETRANSFER_TIME: 0.401,
        CurlInfo.STARTTRANSFER_TIME: 0,
        CurlInfo.TOTAL_TIME: 5,
        CurlInfo.HTTP_CONNECTCODE: 200,
    }
    failure = Timeout("DO_NOT_LOG_EXCEPTION_TEXT", 28, response)

    async def failed(*_args, **_kwargs):
        raise failure

    AsyncSession.request = failed
    client = AsyncClient()
    try:
        assert CurlInfo.APPCONNECT_TIME in client.curl_infos, "native timing collection absent"
        try:
            await client.request(
                "GET",
                "https://search.yahoo.com/search?p=DO_NOT_LOG_QUERY",
                headers={"Authorization": "DO_NOT_LOG_HEADER"},
                cookies={"YBV": "DO_NOT_LOG_COOKIE"},
            )
        except Timeout as error:
            assert error is failure, "exception identity changed"
        else:
            raise AssertionError("native error was swallowed")
        captured = [m for m in messages if m.startswith("Yahoo HTTP timing ")]
        assert len(captured) == 1, messages
        message = captured[0]
        assert "appconnect_time" in message and "5000" in message and "28" in message
        assert "DO_NOT_LOG" not in message and "https://" not in message, message
        assert "p=" not in message and "YBV" not in message, message
        messages.clear()
        for url in (
            "https://yahoo.com.invalid/search",
            "https://example.com/search",
            "http://[invalid",
        ):
            try:
                await client.request("GET", url)
            except Timeout as error:
                assert error is failure
        assert not messages, "unrelated or malformed target was logged"

        cancellation = asyncio.CancelledError()

        async def cancelled(*_args, **_kwargs):
            raise cancellation

        AsyncSession.request = cancelled
        try:
            await client.request("GET", "https://search.yahoo.com/search")
        except asyncio.CancelledError as error:
            assert error is cancellation
        else:
            raise AssertionError("cancellation was swallowed")
        assert not messages, "cancellation became an upstream failure"

        async def succeeded(*_args, **_kwargs):
            return response

        AsyncSession.request = succeeded
        response.infos[CurlInfo.TOTAL_TIME] = 0.2
        assert await client.request("GET", "https://search.yahoo.com/search") is response
        assert not messages
        response.infos[CurlInfo.TOTAL_TIME] = 2.5
        assert (
            await client.request("GET", "https://search.yahoo.com/search?p=DO_NOT_LOG_QUERY")
            is response
        )
        assert len(messages) == 1 and "kind=slow" in messages[0] and "2500" in messages[0]
        assert "DO_NOT_LOG" not in messages[0]
        print("PASS: numeric Yahoo timing/privacy; original error/cancellation/success identity")
    finally:
        AsyncSession.request = original
        logger.removeHandler(capture)
        await client.aclose()


asyncio.run(main())
