"""Hold signed observation streams through an E1 measurement window."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

import httpx
from signed_load import _ORIGIN, _exchange

_NODES = ("https://192.168.139.232:28445", "https://192.168.139.154:28445")


@dataclass
class Stream:
    node: int
    first_id: int | None = None
    last_id: int | None = None
    opened: float | None = None
    closed: float | None = None
    status: int | None = None
    failure: str | None = None
    keepalives: int = 0
    reason: str | None = None
    renewal_gaps: list[float] = field(default_factory=list)
    renewing_since: float | None = None


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


async def _event_frames(
    lines: AsyncIterator[str], row: Stream
) -> AsyncIterator[tuple[int, tuple[str, ...]]]:
    event_id = None
    data: list[str] = []
    async for line in lines:
        if line.startswith(": keepalive"):
            row.keepalives += 1
            _mark_resumed(row)
        elif line.startswith("id:"):
            event_id = int(line[3:].strip())
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif not line:
            if event_id is not None and data:
                if event_id < 0 or (row.last_id is not None and event_id <= row.last_id):
                    raise ValueError("SSE cursor did not advance")
                row.last_id = event_id
                _mark_resumed(row)
                yield event_id, tuple(data)
            event_id, data = None, []


def _mark_resumed(row: Stream) -> None:
    if row.renewing_since is not None:
        row.renewal_gaps.append(asyncio.get_running_loop().time() - row.renewing_since)
        row.renewing_since = None


@asynccontextmanager
async def hold_streams(
    client: httpx.AsyncClient,
    *,
    task_id: str,
    binding: dict,
    principal_token: str,
    count: int = 256,
    startup_timeout: float = 120,
    renew_after: float | None = None,
) -> AsyncIterator[list[Stream]]:
    if not 1 <= count <= 256 or startup_timeout <= 0:
        raise ValueError("invalid E1 stream inventory")
    if renew_after is not None and not 0 < renew_after < 1800:
        raise ValueError("invalid SSE renewal interval")
    path = f"/tasks/{UUID(task_id)}/stream"
    loop = asyncio.get_running_loop()
    rows = [Stream(index % len(_NODES)) for index in range(count)]
    gates = [asyncio.Lock() for _ in _NODES]
    ready = [asyncio.Event() for _ in rows]

    async def hold(row: Stream, signal: asyncio.Event) -> None:
        response = None
        try:
            while True:
                async with gates[row.node]:
                    signed = await _exchange(client, principal_token, binding)
                    if signed is None:
                        row.failure = "grant_failed"
                        return
                    cursor = row.last_id
                    request = client.build_request(
                        "GET",
                        _NODES[row.node] + path,
                        params={"after_sequence": cursor} if cursor is not None else None,
                        headers={"Authorization": "Bearer " + signed, "Origin": _ORIGIN},
                    )
                    response = await client.send(request, stream=True, follow_redirects=False)
                    row.status = response.status_code
                    content_type = response.headers.get("content-type", "")
                    if row.status != 200 or not content_type.startswith("text/event-stream"):
                        row.failure = "invalid_stream_response"
                        if content_type.startswith("application/json"):
                            row.reason = await _problem_code(response)
                        return
                    frames = _event_frames(response.aiter_lines(), row)
                    if cursor is None:
                        first = await anext(frames, None)
                        if first is None:
                            row.failure = "unexpected_eof"
                            return
                        row.first_id = first[0]
                        row.opened = loop.time()
                        signal.set()
                timer = asyncio.timeout(renew_after)
                try:
                    async with timer:
                        async for _ in frames:
                            pass
                except TimeoutError:
                    if not timer.expired() or row.renewing_since is not None:
                        raise
                    row.renewing_since = loop.time()
                    await response.aclose()
                    response = None
                else:
                    row.failure = "unexpected_eof"
                    return
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
        if any(row.closed is not None or row.renewing_since is not None for row in rows):
            raise StreamWindowError("E1 SSE inventory dropped during the measurement window", rows)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def verify_cross_node_resume(
    client: httpx.AsyncClient,
    *,
    task_id: str,
    binding: dict,
    principal_token: str,
) -> tuple[int, int]:
    path = f"/tasks/{UUID(task_id)}/stream"

    @asynccontextmanager
    async def frames_at(node: int, cursor: int | None = None):
        signed = await _exchange(client, principal_token, binding)
        if signed is None:
            raise RuntimeError("stream recovery grant unavailable")
        async with client.stream(
            "GET",
            _NODES[node] + path,
            headers={"Authorization": "Bearer " + signed, "Origin": _ORIGIN},
            params={"after_sequence": cursor} if cursor is not None else None,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("text/event-stream"):
                raise RuntimeError("expected a raw SSE stream")
            yield _event_frames(response.aiter_lines(), Stream(node, last_id=cursor))

    async with asyncio.timeout(15):
        async with frames_at(0) as original:
            first, successor = await anext(original), await anext(original)
        async with frames_at(1, first[0]) as resumed:
            if await anext(resumed) != successor:
                raise RuntimeError("cross-node resume did not return the exact successor frame")
    return first[0], successor[0]


async def _check() -> None:
    from uuid import uuid4

    from signed_load import _BROKER

    async def truncated():
        yield "id: 1"
        yield "data: {}"

    assert [value async for value in _event_frames(truncated(), Stream(0))] == []
    release = asyncio.Event()
    grants = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"id: 0\ndata: {}\n\n"
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
                assert all(row.first_id == row.last_id == 0 for row in rows)
                release.set()
                while any(row.closed is None for row in rows):
                    await asyncio.sleep(0)
        except RuntimeError as exc:
            assert str(exc) == "E1 SSE inventory dropped during the measurement window"
        else:
            raise AssertionError("early stream closure was accepted")


if __name__ == "__main__":
    asyncio.run(_check())
