from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from agent_runtime.mcp_pool import McpHealthState, McpQuarantinedError, McpSessionPool
from agent_runtime.mcp_protocol import McpProtocolError
from agent_tools import McpProxyRequest, McpProxyResponse, parse_mcp_tool_name


@dataclass
class _FakeTransport:
    fail: bool = False
    model_tools: tuple = ()
    closed: bool = False
    calls: int = field(default=0, init=False)

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        self.calls += 1
        if self.fail:
            raise McpProtocolError("boom")
        return McpProxyResponse(output="ok", metadata={})

    def close(self) -> None:
        self.closed = True


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


def _request() -> McpProxyRequest:
    return McpProxyRequest(
        tool_call_id="call-1",
        target=parse_mcp_tool_name("mcp.fixture.echo"),
        arguments={},
        metadata={},
    )


def test_pool_starts_healthy_and_executes() -> None:
    pool = McpSessionPool(_FakeTransport())
    assert pool.health is McpHealthState.HEALTHY
    response = pool.execute(_request())
    assert response.output == "ok"
    assert pool.health is McpHealthState.HEALTHY


def test_failures_escalate_to_quarantine() -> None:
    transport = _FakeTransport(fail=True)
    pool = McpSessionPool(transport, max_failures=3, backoff_schedule=(1.0, 5.0, 30.0))
    for expected in (McpHealthState.DEGRADED, McpHealthState.DEGRADED, McpHealthState.QUARANTINED):
        with pytest.raises(McpProtocolError):
            pool.execute(_request())
        assert pool.health is expected


def test_quarantined_acquire_raises_within_backoff_window() -> None:
    clock = _Clock()
    pool = McpSessionPool(
        _FakeTransport(fail=True),
        max_failures=1,
        backoff_schedule=(1.0, 5.0, 30.0),
        clock=clock,
    )
    with pytest.raises(McpProtocolError):
        pool.execute(_request())
    assert pool.health is McpHealthState.QUARANTINED
    # still inside the 1.0s window
    with pytest.raises(McpQuarantinedError):
        pool.acquire()
    # window elapses -> probe allowed, leaves quarantine
    clock.advance(1.5)
    pool.acquire()
    assert pool.health is McpHealthState.DEGRADED


def test_success_resets_to_healthy() -> None:
    transport = _FakeTransport(fail=True)
    pool = McpSessionPool(transport, max_failures=3)
    with pytest.raises(McpProtocolError):
        pool.execute(_request())
    assert pool.health is McpHealthState.DEGRADED
    transport.fail = False
    pool.execute(_request())
    assert pool.health is McpHealthState.HEALTHY


def test_backoff_schedule_is_bounded() -> None:
    clock = _Clock()
    pool = McpSessionPool(
        _FakeTransport(fail=True),
        max_failures=1,
        backoff_schedule=(1.0, 5.0, 30.0),
        clock=clock,
    )
    for expected_wait, advance in ((1.0, 1.5), (5.0, 5.5), (30.0, 30.5), (30.0, 30.5)):
        with pytest.raises(McpProtocolError):
            pool.execute(_request())
        assert pool.health is McpHealthState.QUARANTINED
        # quarantined_until moved by the bounded slot (capped at 30.0)
        assert pool._quarantined_until == clock.now + expected_wait
        clock.advance(advance)  # elapse the window so the next execute can probe
        pool.acquire()


def test_close_delegates_to_transport() -> None:
    transport = _FakeTransport()
    pool = McpSessionPool(transport)
    pool.close()
    assert transport.closed is True
