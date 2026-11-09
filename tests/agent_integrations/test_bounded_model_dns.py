"""Real DNS subprocesses must finish or be killed/reaped before returning."""

import asyncio
import os
import socket
import sys

import pytest


def test_domain_resolves_without_parent_dns_threads(monkeypatch):
    from agent_integrations.bounded_model_dns import model_io_loop

    def forbidden(*args, **kw):
        raise AssertionError("parent threaded DNS ran")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    with asyncio.Runner(loop_factory=model_io_loop) as runner:
        result = runner.run(_lookup())
    assert result and all(row[0] in (socket.AF_INET, socket.AF_INET6) for row in result)


async def _lookup():
    return await asyncio.get_running_loop().getaddrinfo("localhost", 443, type=socket.SOCK_STREAM)


def test_cancel_hanging_dns_kills_and_reaps_exact_child(monkeypatch):
    from agent_integrations.bounded_model_dns import model_io_loop

    original = asyncio.create_subprocess_exec
    owned = []

    async def slow(*args, **kwargs):
        child = await original(sys.executable, "-I", "-c", "import time;time.sleep(30)", **kwargs)
        owned.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow)

    async def timed():
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await _lookup()

    with asyncio.Runner(loop_factory=model_io_loop) as runner:
        runner.run(timed())
    assert len(owned) == 1 and owned[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(owned[0].pid, 0)


def test_numeric_address_uses_no_dns_child(monkeypatch):
    from agent_integrations.bounded_model_dns import model_io_loop

    async def forbidden(*args, **kwargs):
        raise AssertionError("numeric address spawned DNS")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    with asyncio.Runner(loop_factory=model_io_loop) as runner:
        result = runner.run(_numeric())
    assert result[0][4][0] == "127.0.0.1"


async def _numeric():
    return await asyncio.get_running_loop().getaddrinfo("127.0.0.1", 443, type=socket.SOCK_STREAM)


def test_repeated_cancel_during_spawn_still_recovers_and_reaps_child(monkeypatch):
    from agent_integrations.bounded_model_dns import model_io_loop

    original = asyncio.create_subprocess_exec
    owned = []

    async def delayed_handle(*args, **kwargs):
        child = await original(sys.executable, "-I", "-c", "import time;time.sleep(30)", **kwargs)
        owned.append(child)
        await asyncio.sleep(0.15)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_handle)

    async def run():
        lookup = asyncio.create_task(_lookup())
        while not owned:
            await asyncio.sleep(0.001)
        lookup.cancel()
        await asyncio.sleep(0.02)
        lookup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await lookup

    with asyncio.Runner(loop_factory=model_io_loop) as runner:
        runner.run(run())
    assert len(owned) == 1 and owned[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(owned[0].pid, 0)


def test_real_resolver_gaierror_is_propagated_and_reaped(monkeypatch):
    from agent_integrations.bounded_model_dns import model_io_loop

    original = asyncio.create_subprocess_exec
    owned = []

    async def track(*args, **kwargs):
        process = await original(*args, **kwargs)
        owned.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", track)

    async def invalid_numeric():
        await asyncio.get_running_loop().getaddrinfo(
            "not-a-number", 443, flags=socket.AI_NUMERICHOST,
        )

    with asyncio.Runner(loop_factory=model_io_loop) as runner:
        with pytest.raises(socket.gaierror) as error:
            runner.run(invalid_numeric())
    assert error.value.errno == socket.EAI_NONAME
    assert len(owned) == 1 and owned[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(owned[0].pid, 0)


def test_repeated_cancel_while_reaping_confirms_original_child_exit(monkeypatch):
    from agent_integrations.bounded_model_dns import _reap, model_io_loop

    async def run():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", "import time; time.sleep(30)",
        )
        original_wait = process.wait
        entered = asyncio.Event()

        async def delayed_wait():
            entered.set()
            await asyncio.sleep(0.1)
            return await original_wait()

        monkeypatch.setattr(process, "wait", delayed_wait)
        reaping = asyncio.create_task(_reap(process))
        await entered.wait()
        reaping.cancel()
        await asyncio.sleep(0.01)
        reaping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reaping
        assert process.returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)

    with asyncio.Runner(loop_factory=model_io_loop) as runner:
        runner.run(run())


def test_guarded_transport_reaches_real_localhost_tls(tmp_path, monkeypatch):
    import json
    import ssl
    import subprocess
    import threading
    from hashlib import sha256
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from types import SimpleNamespace

    import certifi
    from agent_core.ports.worker_budget import ModelRequestBudget
    from agent_integrations.worker_budget import guarded_completion

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True, timeout=10)
    monkeypatch.setattr(certifi, "where", lambda: str(cert))
    received, settled = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Length", "11")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    server = HTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    gate = SimpleNamespace(
        before_model=lambda request: request, check=lambda: 5,
        after_model=lambda reservation, payload: settled.append(payload),
    )
    gateway = SimpleNamespace(
        _client=None, authority_check=None, worker_budget=gate,
        _base_url=f"https://localhost:{server.server_port}", _headers=lambda: {},
        model_request_budget=lambda exact: ModelRequestBudget(
            exact, sha256(exact).hexdigest(), len(exact), 5, "test-byte-meter/1",
        ),
    )
    try:
        result = guarded_completion(gateway, {"max_tokens": 5}, lambda value: value)
        assert result == {"ok": True} and settled == [result]
        assert received == [("/chat/completions", json.dumps(
            {"max_tokens": 5}, separators=(",", ":"),
        ).encode())]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)
        assert not thread.is_alive()
