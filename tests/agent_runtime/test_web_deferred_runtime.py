"""Audited native Web calls need egress, not a disposable OCI workspace."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.deferred import DeferredRuntime
from agent_runtime.harness import LocalToolGateway
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_runtime.web_search import LocalWebSearchTransport


def call(name: str) -> ToolCall:
    return ToolCall(tool_call_id=new_tool_call_id(), name=name, created_at=datetime.now(UTC),
                    arguments={"query": "release"} if name == "web.search" else
                    {"url": "https://example.com/release"} if name == "web.fetch" else {})


def test_default_web_skips_provision_but_later_workspace_call_prepares_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = []
    runtime = LocalRuntime()

    def prepare():
        prepared.append(True)
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    def native(operation, arguments, check, **kwargs):
        check()
        if operation == "fetch":
            return {"text": "release", "status_code": 200,
                    "content_type": "text/plain", "byte_count": 7}
        return {"results": [{"title": "release", "url": "https://example.com/release",
                              "snippet": "release"}], "provider": "probe", "byte_count": 7}

    monkeypatch.setattr("agent_runtime.web_gateway._native_network_call", native)
    monkeypatch.setattr("agent_runtime.web_search._native_network_call", native)
    deferred = DeferredRuntime(prepare)
    gateway = LocalToolGateway(tmp_path, runtime=deferred,
                               web_search_endpoint="https://search.example.com/",
                               network_cancellation_check=lambda: None)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(gateway.execute, [call("web.search"), call("web.fetch")]))
        assert all(result.status is ToolCallStatus.EXECUTED for result in results)
        assert prepared == []
        for _ in range(2):
            assert gateway.execute(call("files.list")).status is ToolCallStatus.EXECUTED
        assert prepared == [True]
    finally:
        gateway.close()
        deferred.close()


@pytest.mark.parametrize("name", ["web.fetch", "web.search"])
@pytest.mark.parametrize("subclass", [False, True])
def test_injected_web_keeps_runtime_requirement(tmp_path: Path, name: str, subclass: bool) -> None:
    class CustomFetch(LocalWebGatewayTransport):
        pass

    class CustomSearch(LocalWebSearchTransport):
        pass

    def prepare():
        raise RuntimeError("runtime required")

    deferred = DeferredRuntime(prepare)
    gateway = LocalToolGateway(
        tmp_path, runtime=deferred, web_search_endpoint="https://search.example.com/",
        **({"web_gateway_transport": (CustomFetch if subclass else LocalWebGatewayTransport)()}
           if name == "web.fetch" else {
            "web_search_transport": (CustomSearch if subclass else LocalWebSearchTransport)()
        }),
    )
    try:
        with pytest.raises(RuntimeError, match="runtime required"):
            gateway.execute(call(name))
    finally:
        gateway.close()
        deferred.close()


def test_native_pipeline_keeps_runtime_requirement(tmp_path: Path) -> None:
    def prepare():
        raise RuntimeError("runtime required")

    deferred = DeferredRuntime(prepare)
    gateway = LocalToolGateway(tmp_path, runtime=deferred, web_pipeline_v2=True)
    try:
        with pytest.raises(RuntimeError, match="runtime required"):
            gateway.execute(call("web.fetch"))
    finally:
        gateway.close()
        deferred.close()


def test_stopped_native_web_neither_prepares_nor_enters_handler(tmp_path: Path) -> None:
    def fail():
        raise AssertionError("stopped tool must not provision")

    def stopped():
        raise asyncio.CancelledError("Task stopped")

    deferred = DeferredRuntime(fail)
    gateway = LocalToolGateway(tmp_path, runtime=deferred, network_cancellation_check=stopped)
    try:
        with pytest.raises(asyncio.CancelledError, match="Task stopped"):
            gateway.execute(call("web.fetch"))
    finally:
        gateway.close()
        deferred.close()
