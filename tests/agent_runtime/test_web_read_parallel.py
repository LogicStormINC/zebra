"""Actual built-in registration, overlap and cancellation without public network I/O."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime.harness import LocalToolGateway
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_runtime.web_search import LocalWebSearchTransport


def call(name: str, index: int) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments={"query": f"release {index}"} if name == "web.search" else {
            "url": f"https://example.com/{index}"
        },
        created_at=datetime.now(UTC),
    )


def test_builtin_search_and_fetch_share_two_slots_and_keep_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier, lock = Barrier(2), Lock()
    active = maximum = 0

    def native(operation, arguments, check, **kwargs):
        nonlocal active, maximum
        check()
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            barrier.wait(timeout=3)
            if operation == "fetch":
                return {"text": arguments["target"]["url"], "status_code": 200,
                        "content_type": "text/plain", "byte_count": 10}
            return {"results": [{"title": arguments["query"],
                                  "url": "https://example.com/release", "snippet": "release"}],
                    "provider": "probe", "byte_count": 10}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr("agent_runtime.web_gateway._native_network_call", native)
    monkeypatch.setattr("agent_runtime.web_search._native_network_call", native)
    gateway = LocalToolGateway(tmp_path, web_search_endpoint="https://search.example.com/",
                               network_cancellation_check=lambda: None)
    try:
        assert {"web.fetch", "web.search"} <= gateway.parallel_safe_tools
        calls = tuple(call(name, i) for i, name in enumerate(
            ("web.fetch", "web.search", "web.fetch", "web.search")
        ))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(gateway.execute, calls))
        assert maximum == 2
        for request, result in zip(calls, results, strict=True):
            assert result.status is ToolCallStatus.EXECUTED
            assert result.tool_call_id == request.tool_call_id
            assert str(next(iter(request.arguments.values()))) in result.output
    finally:
        gateway.close()


@pytest.mark.parametrize("name", ["web.fetch", "web.search"])
@pytest.mark.parametrize("subclass", [False, True])
def test_injected_transport_stays_sequential(tmp_path: Path, name: str, subclass: bool) -> None:
    # Even a subclass of the built-in can add mutable state: require exact audited type.
    class CustomFetch(LocalWebGatewayTransport):
        pass

    class CustomSearch(LocalWebSearchTransport):
        pass

    gateway = LocalToolGateway(
        tmp_path, web_search_endpoint="https://search.example.com/",
        **({"web_gateway_transport": (CustomFetch if subclass else LocalWebGatewayTransport)()}
           if name == "web.fetch" else {
            "web_search_transport": (CustomSearch if subclass else LocalWebSearchTransport)()
        }),
    )
    try:
        assert name not in gateway.parallel_safe_tools
        assert {"web.crawl", "command.run", "files.write"}.isdisjoint(gateway.parallel_safe_tools)
    finally:
        gateway.close()


def test_parallel_web_stop_reaches_both_calls_and_queued_work_does_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier, stopped = Barrier(2), Event()
    signal = asyncio.CancelledError("Task stopped")
    started: list[str] = []

    def check() -> None:
        if stopped.is_set():
            raise signal

    def native(operation, arguments, callback, **kwargs):
        callback()
        started.append(operation)
        barrier.wait(timeout=3)
        stopped.set()
        callback()
        raise AssertionError("stopped result must not escape")

    monkeypatch.setattr("agent_runtime.web_gateway._native_network_call", native)
    monkeypatch.setattr("agent_runtime.web_search._native_network_call", native)
    gateway = LocalToolGateway(tmp_path, web_search_endpoint="https://search.example.com/",
                               network_cancellation_check=check)
    try:
        assert {"web.fetch", "web.search"} <= gateway.parallel_safe_tools
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(gateway.execute, call(name, i)) for i, name in enumerate(
                ("web.fetch", "web.search", "web.fetch")
            )]
            for future in futures:
                with pytest.raises(asyncio.CancelledError) as caught:
                    future.result()
                assert caught.value is signal
        assert len(started) == 2
    finally:
        gateway.close()
