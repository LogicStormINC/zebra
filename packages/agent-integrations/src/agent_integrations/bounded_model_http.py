"""Small, non-streaming auxiliary model requests with explicit resource bounds."""

import asyncio
import json
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from time import monotonic
from typing import Any

import httpx
from agent_core.domain.modeling import ModelInvocationPolicy, ModelThinkingMode, ModelToolChoice


def validate_bounded_policy(policy: ModelInvocationPolicy | None, *, has_tools: bool) -> int:
    if (
        has_tools
        or policy is None
        or policy.thinking_mode is not ModelThinkingMode.DISABLED
        or policy.tool_choice is not ModelToolChoice.NONE
        or policy.max_output_tokens is None
        or not 1 <= policy.max_output_tokens <= 128
    ):
        raise ValueError(
            "bounded expression requires tools/thinking disabled and a small output cap"
        )
    return policy.max_output_tokens


class _NoThreadedIO(ThreadPoolExecutor):
    def submit[T](self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        # ponytail: native DNS uses uncancellable threads. Fall back for that path
        # until a cancellable resolver is composed; numeric endpoints/proxies work.
        raise ValueError("auxiliary model HTTP cannot safely cancel threaded I/O (DNS)")


def _bounded_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    loop.set_default_executor(_NoThreadedIO(max_workers=1))
    return loop


def post_bounded_json(
    client: httpx.Client | None,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    deadline_s: float,
) -> dict[str, Any]:
    if not 0 < deadline_s <= 2:
        raise ValueError("auxiliary model deadline must be between zero and two seconds")
    if client is not None:
        raise ValueError("auxiliary model HTTP cannot safely cancel an injected synchronous client")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise ValueError("auxiliary model HTTP cannot block a running event loop")
    started = monotonic()
    with asyncio.Runner(loop_factory=_bounded_loop) as runner:
        return runner.run(_post(url, headers, body, deadline_s=deadline_s, started=started))


async def _post(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    deadline_s: float,
    started: float,
) -> dict[str, Any]:
    content = bytearray()
    request_headers = httpx.Headers(headers)
    request_headers["Accept-Encoding"] = "identity"
    # One cancellation scope covers connection, headers, body and socket cleanup.
    async with asyncio.timeout(deadline_s - (monotonic() - started)):
        async with httpx.AsyncClient(timeout=httpx.Timeout(deadline_s)) as client:
            async with client.stream("POST", url, headers=request_headers, json=body) as response:
                response.raise_for_status()
                if (
                    response.headers.get("Content-Encoding", "identity").strip().lower()
                    != "identity"
                ):
                    raise ValueError("public expression response has unexpected content encoding")
                length = response.headers.get("Content-Length")
                if length is not None and not 0 <= int(length) <= 32_768:
                    raise ValueError("public expression response exceeds size bound")
                async for chunk in response.aiter_raw():
                    if len(content) + len(chunk) > 32_768:
                        raise ValueError("public expression response exceeds size bound")
                    content.extend(chunk)
    if monotonic() - started >= deadline_s:
        raise TimeoutError("public expression deadline exceeded")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("public expression response must be an object")
    if monotonic() - started >= deadline_s:
        raise TimeoutError("public expression deadline exceeded")
    return result
