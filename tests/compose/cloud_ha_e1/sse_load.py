"""Hold signed observation streams through an E1 measurement window."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

import httpx
from signed_load import _ORIGIN, _exchange

_NODES = ("https://192.168.139.232:28445", "https://192.168.139.154:28445")


@dataclass
class Stream:
    node: int
    first_id: str | None = None
    opened: float | None = None
    closed: float | None = None
    status: int | None = None
    failure: str | None = None
    keepalives: int = 0
    reason: str | None = None


class StreamWindowError(RuntimeError):
    def __init__(self, message: str, rows: list[Stream]) -> None:
        super().__init__(message)
        self.rows = rows


async def _problem_code(response: httpx.Response) -> str | None:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        if len(data) + len(chunk) > 4096:
            return None
        data.extend(chunk)
    try:
        body = json.loads(data)
    except ValueError:
        return None
    if isinstance(body, dict):
        error = body.get("error")
        nested_code = error.get("code") if isinstance(error, dict) else error
        for value in (body.get("reason"), body.get("code"), nested_code):
            if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value):
                return value
    return None


@asynccontextmanager
async def hold_streams(
    client: httpx.AsyncClient,
    *,
    task_id: str,
    binding: dict,
    principal_token: str,
    count: int = 256,
    startup_timeout: float = 120,
) -> AsyncIterator[list[Stream]]:
    if not 1 <= count <= 256 or startup_timeout <= 0:
        raise ValueError("invalid E1 stream inventory")
    path = f"/tasks/{UUID(task_id)}/stream"
    loop = asyncio.get_running_loop()
    rows = [Stream(index % len(_NODES)) for index in range(count)]
    gates = [asyncio.Lock() for _ in _NODES]
    ready = [asyncio.Event() for _ in rows]

    async def hold(row: Stream, signal: asyncio.Event) -> None:
        response = None
        try:
            async with gates[row.node]:
                signed = await _exchange(client, principal_token, binding)
                if signed is None:
                    row.failure = "grant_failed"
                    return
                request = client.build_request(
                    "GET",
                    _NODES[row.node] + path,
                    headers={"Authorization": "Bearer " + signed, "Origin": _ORIGIN},
                )
                response = await client.send(request, stream=True, follow_redirects=False)
                row.status = response.status_code
                if row.status != 200 or not response.headers.get("content-type", "").startswith(
                    "text/event-stream"
                ):
                    row.failure = "invalid_stream_response"
                    if response.headers.get("content-type", "").startswith("application/json"):
                        row.reason = await _problem_code(response)
                    return
                lines = response.aiter_lines()
                async for line in lines:
                    if line.startswith("id:") and line[3:].strip():
                        row.first_id = line[3:].strip()
                        row.opened = loop.time()
                        signal.set()
                        break
            async for line in lines:
                if line.startswith(": keepalive"):
                    row.keepalives += 1
            row.failure = "unexpected_eof"
        except Exception as exc:
            row.failure = type(exc).__name__
        finally:
            row.closed = loop.time()
            signal.set()
            if response is not None:
                await response.aclose()

    tasks = [asyncio.create_task(hold(row, event)) for row, event in zip(rows, ready, strict=True)]
    try:
        try:
            async with asyncio.timeout(startup_timeout):
                await asyncio.gather(*(event.wait() for event in ready))
        except TimeoutError as exc:
            raise StreamWindowError("E1 SSE readiness barrier timed out", rows) from exc
        if any(row.opened is None or row.closed is not None for row in rows):
            raise StreamWindowError("E1 SSE readiness barrier failed", rows)
        yield rows
        if any(row.closed is not None for row in rows):
            raise StreamWindowError("E1 SSE inventory dropped during the measurement window", rows)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _check() -> None:
    from uuid import uuid4

    from signed_load import _BROKER

    release = asyncio.Event()
    grants = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"id: original\ndata: {}\n\n"
            await release.wait()

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _BROKER:
            grant = str(uuid4())
            grants.append(grant)
            return httpx.Response(200, json={"grant": grant})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        try:
            async with hold_streams(
                client, task_id=str(uuid4()), binding={}, principal_token="test", count=4
            ) as rows:
                assert len(grants) == len(set(grants)) == len(rows) == 4
                assert all(row.first_id == "original" for row in rows)
                release.set()
                while any(row.closed is None for row in rows):
                    await asyncio.sleep(0)
        except RuntimeError as exc:
            assert str(exc) == "E1 SSE inventory dropped during the measurement window"
        else:
            raise AssertionError("early stream closure was accepted")


if __name__ == "__main__":
    asyncio.run(_check())
