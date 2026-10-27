"""Bounded streaming and retained threads for pure scoped validation adapters."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect
from starlette.routing import Route

from zebra_agent_api.runtime_management import _HEADERS, _error


async def _body(request: Request, max_bytes: int) -> bytes:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > max_bytes:
            raise ValueError("BODY_TOO_LARGE")
        raw.extend(chunk)
    if request.method == "GET" and raw:
        raise ValueError("GET_BODY_FORBIDDEN")
    length = request.headers.get("content-length")
    if length is not None and len(raw) != int(length):
        raise ValueError("BODY_LENGTH_MISMATCH")
    return bytes(raw)


def register_validation_routes(
    app: FastAPI,
    perform: Callable[[str, dict[str, list[str]], str, str | None, bytes], JSONResponse],
    *,
    contract_path: str,
    validation_path: str,
    token_pattern: str,
    contract_header: str,
    max_bytes: int,
    actions: tuple[str, str],
    body_timeout: float,
    request_timeout: float,
) -> None:
    slots = asyncio.Semaphore(8)

    async def handle(request: Request) -> JSONResponse:
        method = "GET" if request.url.path.endswith(contract_path) else "POST"
        if request.method != method:
            response = _error(405, "METHOD_NOT_ALLOWED")
            response.headers["Allow"] = method
            return response
        tokens = request.headers.getlist("authorization")
        if len(tokens) != 1:
            return _error(401, "UNAUTHENTICATED")
        scheme, _, token = tokens[0].partition(" ")
        if scheme.lower() != "bearer" or re.fullmatch(token_pattern, token) is None:
            return _error(401, "UNAUTHENTICATED")
        if (
            request.url.query
            or request.headers.getlist("cookie")
            or request.headers.getlist("content-encoding")
            or any(
                len(request.headers.getlist(name)) > 1
                for name in (
                    *_HEADERS.values(),
                    "content-type",
                    "content-length",
                    "transfer-encoding",
                    contract_header,
                )
            )
        ):
            return _error(400, "INVALID_ARGUMENT")
        contract_headers = request.headers.getlist(contract_header)
        if method == "POST" and (
            request.headers.getlist("content-type") != ["application/json"]
            or len(contract_headers) != 1
        ):
            return _error(400, "INVALID_ARGUMENT")
        lengths = request.headers.getlist("content-length")
        if lengths and (
            re.fullmatch(r"[0-9]+", lengths[0]) is None
            or len(lengths[0]) > 7
            or int(lengths[0]) > (max_bytes if method == "POST" else 0)
        ):
            return _error(400, "INVALID_ARGUMENT")
        if request.headers.getlist("transfer-encoding") and (
            lengths
            or request.headers.getlist("transfer-encoding") != ["chunked"]
            or method == "GET"
        ):
            return _error(400, "INVALID_ARGUMENT")
        if slots.locked():
            response = _error(429, "RATE_LIMITED")
            response.headers["Retry-After"] = "1"
            return response
        await slots.acquire()
        try:
            raw = await asyncio.wait_for(_body(request, max_bytes), body_timeout)
        except (ValueError, TypeError, RecursionError, TimeoutError, ClientDisconnect):
            slots.release()
            return _error(400, "INVALID_ARGUMENT")
        except BaseException:
            slots.release()
            raise
        headers = {name: request.headers.getlist(name) for name in _HEADERS.values()}
        action = actions[0] if method == "GET" else actions[1]
        task = asyncio.create_task(
            asyncio.to_thread(
                perform,
                token,
                headers,
                action,
                contract_headers[0] if contract_headers else None,
                raw,
            )
        )

        def finished(done: asyncio.Task[JSONResponse]) -> None:
            slots.release()
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), request_timeout)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            RecursionError,
            TimeoutError,
        ):
            return _error(503, "MANAGEMENT_UNAVAILABLE")

    for path in (contract_path, validation_path):
        route = Route(path, handle)
        route.methods = None  # Include extension methods in the scoped fixed-error handler.
        app.router.routes.append(route)
