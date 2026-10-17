"""No model: original DoH parser and actual bounded persistent child protocol."""

import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Event
from time import monotonic

import pytest
from agent_core.domain.web import parse_web_target
from agent_runtime import public_dns
from agent_runtime.doh_transport import DohTransport, current_doh_transport
from agent_runtime.native_network_scope import DohNetworkScope
from agent_runtime.web_gateway import _native_network_call, sticky_network_cancellation_check
from agent_tools.web_gateway import WebGatewayError, WebGatewayRequest

from tests.agent_runtime.test_crawl_source_http import native_tls_source
from tests.agent_runtime.test_native_network_cancellation import native_connect_proxy
from tests.agent_runtime.test_web_gateway_transport import FakeOpener, FakeResponse


def test_fresh_doh_parser_and_connection_reuse(monkeypatch):
    from unittest.mock import Mock

    connection = Mock()
    transport = DohTransport()
    instances = Mock(return_value=connection)
    monkeypatch.setattr("http.client.HTTPSConnection", instances)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.3", 443))],
    )
    payload = {
        "Status": 0,
        "Question": [{"name": "one.example", "type": 1}],
        "Answer": [{"type": 1, "data": "1.1.1.1"}],
    }
    connection.getresponse.side_effect = [
        FakeResponse(json.dumps(payload).encode()) for _ in range(2)
    ]
    token = current_doh_transport.set(transport)
    try:
        for _ in range(2):
            assert public_dns.public_addresses("one.example", 443)[0][4][0] == "1.1.1.1"
        assert instances.call_count == 1 and connection.request.call_count == 2
        payload["Answer"][0]["data"] = "127.0.0.1"
        connection.getresponse.side_effect = None
        connection.getresponse.return_value = FakeResponse(json.dumps(payload).encode())
        with pytest.raises(public_dns.PublicAddressBlocked):
            public_dns.public_addresses("one.example", 443)
        assert connection.request.call_count == 3
        payload["Question"][0]["name"] = "wrong.example"
        connection.getresponse.return_value = FakeResponse(json.dumps(payload).encode())
        with pytest.raises(OSError, match="question mismatch"):
            public_dns.public_addresses("one.example", 443)
        connection.close.assert_called()
    finally:
        current_doh_transport.reset(token)
        transport.close()


def test_default_keeps_existing_opener(monkeypatch):
    opener = FakeOpener(FakeResponse(b'{"Status":2}'))
    monkeypatch.setattr(public_dns.urllib.request, "build_opener", lambda *a: opener)
    with pytest.raises(OSError):
        public_dns._doh_addresses("example.com")
    assert current_doh_transport.get() is None


def scope_call(scope, operation, arguments, **kwargs):
    return _native_network_call(
        operation,
        arguments,
        scope,
        timeout=kwargs.pop("timeout", 3),
        max_output_bytes=kwargs.pop("maximum", 65536),
        **kwargs,
    )


def instrument_child(monkeypatch):
    original = subprocess.Popen
    children = []

    def start(args, **kwargs):
        # Private test injection into the real child protocol, never production config.
        if "native_network_scope" in args[-1]:
            args = [
                *args[:-1],
                "import time; from agent_runtime import public_dns as d; "
                "d.public_host_ips=lambda host: (time.sleep(5) or ('1.1.1.1',)) "
                "if host=='slow.example' else ('1.1.1.1',); " + args[-1],
            ]
        child = original(args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", start)
    return children


def test_actual_children_reuse_bounds_revocation_and_close(monkeypatch):
    children = instrument_child(monkeypatch)
    revoked = Event()
    checks = []

    def check():
        checks.append(1)
        if revoked.is_set():
            raise InterruptedError("authority revoked")

    scope = sticky_network_cancellation_check(check, reuse_doh=True)
    assert isinstance(scope, DohNetworkScope)
    try:
        for _ in range(3):
            assert scope_call(scope, "resolve", "one.example") is None
        assert len(children) == 1 and len(checks) >= 9
        with pytest.raises(WebGatewayError, match="bound|ended"):
            scope_call(scope, "resolve", "one.example", maximum=1)
        assert children[0].poll() is not None
        assert scope_call(scope, "resolve", "one.example") is None
        revoked.set()
        with pytest.raises(InterruptedError):
            scope_call(scope, "resolve", "one.example")
        assert len(children) == 2
    finally:
        scope.close()
    assert all(child.poll() is not None and child.stdout.closed for child in children)


def test_request_cancel_preserves_sibling_and_recovery(monkeypatch):
    children = instrument_child(monkeypatch)
    cancel = Event()
    # Scope is execution-owned; separate per-request test flag simulates one caller interrupt.
    import threading

    def check():
        if cancel.is_set() and threading.current_thread().name.startswith("cancel-lane"):
            raise InterruptedError("request interrupted")

    scope = DohNetworkScope(check)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix="cancel-lane") as pool:
            slow = pool.submit(scope_call, scope, "resolve", "slow.example")
            deadline = monotonic() + 2
            while not children:
                assert monotonic() < deadline
                cancel.wait(0.01)
            assert scope_call(scope, "resolve", "one.example") is None
            start = monotonic()
            cancel.set()
            with pytest.raises(InterruptedError):
                slow.result(timeout=1)
            assert monotonic() - start < 0.75
        assert scope_call(scope, "resolve", "one.example") is None
        assert len(children) == 2
    finally:
        scope.close()
    assert all(child.poll() is not None for child in children)


def test_actual_tls_read_cancel_closes_peer(tmp_path, monkeypatch):
    cancelled = Event()

    def check():
        if cancelled.is_set():
            raise InterruptedError("read revoked")

    scope = DohNetworkScope(check)
    with native_connect_proxy(monkeypatch) as target:
        with native_tls_source(tmp_path, monkeypatch, "drip", on_listen=target.append) as (
            requests,
            entered,
            closed,
            release,
            writes,
        ):
            with ThreadPoolExecutor(1) as pool:
                pending = pool.submit(
                    scope_call,
                    scope,
                    "fetch",
                    asdict(
                        WebGatewayRequest(
                            "probe", parse_web_target("https://source.example/article")
                        )
                    ),
                    use_system_proxy=True,
                )
                try:
                    assert entered.wait(2)
                    cancelled.set()
                    with pytest.raises(InterruptedError):
                        pending.result(timeout=1)
                    assert closed.wait(0.5) and not release.is_set()
                    assert len(requests) == 1
                finally:
                    release.set()
                    scope.close()


def test_scope_idle_retirement_failure_recovery_and_deadline(monkeypatch):
    children = instrument_child(monkeypatch)
    scope = DohNetworkScope(lambda: None)
    try:
        assert scope_call(scope, "resolve", "one.example") is None
        child, _ = scope._idle[0]
        scope._idle[0] = (child, monotonic() - 16)
        assert scope_call(scope, "resolve", "one.example") is None
        assert children[0].poll() is not None and len(children) == 2
        with pytest.raises(WebGatewayError):
            scope_call(scope, "invalid", "one.example")
        assert len(children) == 2  # No automatic replay.
        with pytest.raises(WebGatewayError, match="deadline"):
            scope_call(scope, "resolve", "slow.example", timeout=0.1)
        assert children[-1].poll() is not None
        assert scope_call(scope, "resolve", "one.example") is None
    finally:
        scope.close()
    assert all(c.poll() is not None for c in children)
    with pytest.raises(WebGatewayError, match="closed"):
        scope_call(scope, "resolve", "one.example")


def test_gateway_explicit_opt_in_and_close(tmp_path):
    from agent_runtime.harness import LocalToolGateway

    for enabled in (False, True):
        gateway = LocalToolGateway(
            tmp_path, network_cancellation_check=lambda: None, reuse_doh_transport=enabled
        )
        check = gateway._network_check
        assert isinstance(check, DohNetworkScope) is enabled
        gateway.close()
        if enabled:
            with pytest.raises(WebGatewayError, match="closed"):
                check()


def test_busy_lanes_keep_queue_deadline_and_live_checks(monkeypatch):
    children = instrument_child(monkeypatch)
    cancelled = Event()

    def check():
        if cancelled.is_set():
            raise InterruptedError("execution revoked")

    scope = DohNetworkScope(check)
    try:
        with ThreadPoolExecutor(2) as pool:
            pending = [pool.submit(scope_call, scope, "resolve", "slow.example") for _ in range(2)]
            deadline = monotonic() + 2
            while len(children) < 2:
                assert monotonic() < deadline
                cancelled.wait(0.01)
            with pytest.raises(WebGatewayError, match="deadline"):
                scope_call(scope, "resolve", "one.example", timeout=0.05)
            assert len(children) == 2
            cancelled.set()
            for result in pending:
                with pytest.raises(InterruptedError):
                    result.result(timeout=1)
    finally:
        scope.close()
    assert all(c.poll() is not None for c in children)
