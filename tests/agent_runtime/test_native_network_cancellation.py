"""Actual gateway cancellation: native proxy/TLS, peer EOF, and child reap."""

import asyncio
import os
import select
import signal
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from threading import Event, Thread
from time import monotonic

import pytest
from agent_runtime.crawl_gateway import CrawlGateway
from agent_runtime.harness import LocalToolGateway
from agent_runtime.web_gateway import _native_network_call
from agent_storage.web_resource import SQLiteWebResourceStore
from agent_tools.web_gateway import WebGatewayError

from tests.agent_runtime.test_crawl_source_http import call, native_tls_source


def test_browser_factory_receives_live_task_scoped_cancel_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks: list[Callable[[], None] | None] = []
    canceled = Event()
    signal = asyncio.CancelledError("browser Task canceled")
    calls: list[str] = []

    def check() -> None:
        calls.append("checked")
        if canceled.is_set():
            raise signal

    def factory(*, network_cancellation_check: Callable[[], None] | None = None) -> object:
        checks.append(network_cancellation_check)
        return object()

    monkeypatch.setattr("agent_runtime.web_tools.is_crawl4ai_available", lambda: True)
    monkeypatch.setattr("agent_runtime.web_tools.Crawl4AIFetchProvider", factory)
    gateway = LocalToolGateway(
        tmp_path, trusted_local=True, web_pipeline_v2=True, network_cancellation_check=check
    )
    try:
        assert len(checks) == 1 and checks[0] is not None
        callback = checks[0]
        callback()
        assert calls == ["checked"]
        canceled.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            callback()
        assert caught.value is signal
        with pytest.raises(asyncio.CancelledError) as repeated:
            gateway.execute(call("web.fetch"))
        assert repeated.value is signal and calls == ["checked", "checked"]
    finally:
        gateway.close()


@contextmanager
def native_connect_proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Only route the scratch origin; native urllib still verifies the TLS peer."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.05)
    target: list[int] = []
    stop = Event()
    peers: list[socket.socket] = []
    workers: list[Thread] = []

    def relay(client: socket.socket) -> None:
        upstream = socket.socket()
        peers.append(upstream)
        try:
            client.settimeout(1)
            request = b""
            while b"\r\n\r\n" not in request:
                part = client.recv(4096)
                if not part:
                    return
                request += part
            assert request.startswith(b"CONNECT source.example:443 HTTP/1.")
            assert target
            upstream.connect(("127.0.0.1", target[0]))
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            client.settimeout(None)
            while not stop.is_set():
                ready, _, _ = select.select([client, upstream], [], [], 0.05)
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is client else client).sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()
            client.close()

    def accept() -> None:
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            peers.append(client)
            worker = Thread(target=relay, args=(client,))
            workers.append(worker)
            worker.start()

    thread = Thread(target=accept)
    thread.start()
    with monkeypatch.context() as environment:
        environment.setenv("https_proxy", f"http://127.0.0.1:{listener.getsockname()[1]}")
        environment.setenv("no_proxy", "")
        environment.delenv("NO_PROXY", raising=False)
        try:
            yield target
        finally:
            stop.set()
            listener.close()
            for peer in peers:
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            thread.join(1)
            for worker in workers:
                worker.join(1)
                assert not worker.is_alive()
            assert not thread.is_alive()


def observe_children(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    children: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    def start(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child: subprocess.Popen[bytes] = original(*args, **kwargs)  # type: ignore[call-overload]
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", start)
    return children


@pytest.mark.parametrize(
    "v2,name",
    [
        (False, "web.fetch"),
        (True, "web.fetch"),
        (True, "web.crawl"),
        (True, "web.extract"),
        (False, "web.search"),
        (True, "web.search"),
    ],
)
@pytest.mark.parametrize(
    "signal_type", [asyncio.CancelledError, RuntimeError, SystemExit, KeyboardInterrupt]
)
def test_outer_cancel_stops_native_tls_read_and_reaps_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    v2: bool,
    name: str,
    signal_type: type[BaseException],
) -> None:
    cancelled = Event()
    signal = signal_type("task cancellation or ownership loss")

    def check() -> None:
        if cancelled.is_set():
            raise signal

    children = observe_children(monkeypatch)
    monkeypatch.setattr(
        "agent_runtime.web_tools.CrawlGateway",
        partial(CrawlGateway, resolver=lambda _host: ("93.184.216.34",)),
    )
    with native_connect_proxy(monkeypatch) as target:
        with native_tls_source(tmp_path, monkeypatch, "drip", on_listen=target.append) as (
            requests,
            entered,
            closed,
            release,
            writes,
        ):
            gateway = LocalToolGateway(
                tmp_path,
                trusted_local=True,
                web_pipeline_v2=v2,
                web_search_endpoint="https://source.example/search",
                network_cancellation_check=check,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                native = executor.submit(
                    gateway.execute,
                    call(name, **({"query": "evidence"} if name == "web.search" else {})),
                )

                async def cancel_waiter() -> None:
                    wrapped = asyncio.wrap_future(native)
                    assert await asyncio.to_thread(entered.wait, 2)
                    wrapped.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await wrapped
                    previous = len(writes)
                    await asyncio.sleep(0.08)
                    assert not native.done() and not closed.is_set()
                    assert (
                        len(writes) > previous
                    )  # Canceling a waiter alone leaves native I/O live.
                    cancelled.set()  # The actual Task signal, not Future.cancel() magic.

                try:
                    asyncio.run(cancel_waiter())
                    with pytest.raises(signal_type) as caught:
                        native.result(timeout=1)
                    assert caught.value is signal
                    assert closed.wait(0.5) and not release.is_set()
                    assert len(requests) == 1 and writes
                    assert children and all(child.poll() is not None for child in children)
                    assert all(
                        child.stdout is not None and child.stdout.closed for child in children
                    )
                    assert all(child.stdin is not None and child.stdin.closed for child in children)
                    previous_children = len(children)
                    with pytest.raises(signal_type) as retried:
                        gateway.execute(call("web.fetch"))
                    assert retried.value is signal and len(children) == previous_children
                finally:
                    cancelled.set()
                    release.set()
                    gateway.close()
            if v2:
                store = SQLiteWebResourceStore(
                    tmp_path / ".zebra-agent" / "web_resources.sqlite", tmp_path / "cache"
                )
                with store._database.connect() as connection:
                    assert (
                        connection.execute("SELECT COUNT(*) FROM web_resource").fetchone()[0] == 0
                    )


def test_cancel_stops_native_tls_handshake_before_server_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled, entered, closed, release = Event(), Event(), Event(), Event()
    signal = asyncio.CancelledError("task stopped during TLS handshake")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(2)

    def stall_handshake() -> None:
        try:
            client, _ = listener.accept()
        except OSError:
            return
        with client:
            client.settimeout(0.05)
            first = client.recv(4096)
            assert first.startswith(b"\x16\x03")  # Native TLS ClientHello.
            entered.set()
            while not release.is_set():
                try:
                    if client.recv(4096) == b"":
                        closed.set()
                        return
                except TimeoutError:
                    continue

    thread = Thread(target=stall_handshake)
    thread.start()

    def check() -> None:
        if cancelled.is_set():
            raise signal

    children = observe_children(monkeypatch)
    try:
        with native_connect_proxy(monkeypatch) as target:
            target.append(listener.getsockname()[1])
            gateway = LocalToolGateway(
                tmp_path, trusted_local=True, network_cancellation_check=check
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                native = executor.submit(gateway.execute, call("web.fetch"))
                try:
                    assert entered.wait(2)
                    cancelled.set()
                    with pytest.raises(asyncio.CancelledError) as caught:
                        native.result(timeout=1)
                    assert caught.value is signal
                    assert closed.wait(0.5) and not release.is_set()
                    assert len(children) == 1 and children[0].poll() is not None
                finally:
                    cancelled.set()
                    release.set()
                    gateway.close()
    finally:
        listener.close()
        release.set()
        thread.join(2)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "v2,name",
    [
        (False, "web.fetch"),
        (True, "web.fetch"),
        (True, "web.crawl"),
        (True, "web.extract"),
        (False, "web.search"),
        (True, "web.search"),
    ],
)
@pytest.mark.parametrize("mode", ["normal", "206", "incomplete"])
def test_scoped_native_gateway_preserves_complete_partial_and_failed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    v2: bool,
    name: str,
    mode: str,
) -> None:
    monkeypatch.setattr(
        "agent_runtime.web_tools.CrawlGateway",
        partial(CrawlGateway, resolver=lambda _host: ("93.184.216.34",)),
    )
    children = observe_children(monkeypatch)
    with native_connect_proxy(monkeypatch) as target:
        with native_tls_source(tmp_path, monkeypatch, mode, on_listen=target.append) as (
            requests,
            entered,
            _,
            _,
            _,
        ):
            gateway = LocalToolGateway(
                tmp_path,
                trusted_local=True,
                web_pipeline_v2=v2,
                web_search_endpoint="https://source.example/search",
                network_cancellation_check=lambda: None,
            )
            try:
                result = gateway.execute(
                    call(name, **({"query": "evidence"} if name == "web.search" else {}))
                )
            finally:
                gateway.close()
            assert entered.is_set() and len(requests) == 1
            assert len(children) == 1 and children[0].poll() == 0
    failed = mode == "incomplete" or (name == "web.search" and mode == "206")
    if failed:
        assert result.status.value == "failed" and not result.output
        assert result.metadata["reason"] == (
            "response_incomplete" if mode == "incomplete" else "search_incomplete"
        )
        assert "result_count" not in result.metadata and "web_envelope" not in result.metadata
    else:
        assert result.status.value == "executed"
        assert result.metadata["untrusted_external_content"] is True
        if name == "web.search":
            assert result.metadata["result_count"] == 0
        elif v2:
            assert result.metadata["source_truncated"] is (mode == "206")
            assert result.metadata["projection_truncated"] is False
            assert result.metadata["degraded"] is (mode == "206")
        else:
            assert result.metadata["status_code"] == (206 if mode == "206" else 200)


@pytest.mark.parametrize("name", ["web.fetch", "web.search"])
def test_precancelled_gateway_never_starts_native_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    signal = asyncio.CancelledError("canceled before admission")

    def check() -> None:
        raise signal

    children = observe_children(monkeypatch)
    gateway = LocalToolGateway(
        tmp_path,
        network_cancellation_check=check,
        web_search_endpoint="https://source.example/search",
    )
    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            gateway.execute(call(name, **({"query": "evidence"} if name == "web.search" else {})))
        assert caught.value is signal and not children
    finally:
        gateway.close()


@pytest.mark.parametrize("name", ["web.fetch", "web.search"])
def test_signal_after_native_completion_cannot_publish_or_cache_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    children = observe_children(monkeypatch)
    signal = RuntimeError("ownership lost as the native read completed")

    def check() -> None:
        if children and children[-1].poll() is not None:
            raise signal

    monkeypatch.setattr(
        "agent_runtime.web_tools.CrawlGateway",
        partial(CrawlGateway, resolver=lambda _host: ("93.184.216.34",)),
    )
    with native_connect_proxy(monkeypatch) as target:
        with native_tls_source(tmp_path, monkeypatch, "normal", on_listen=target.append):
            gateway = LocalToolGateway(
                tmp_path,
                trusted_local=True,
                web_pipeline_v2=True,
                web_search_endpoint="https://source.example/search",
                network_cancellation_check=check,
            )
            try:
                with pytest.raises(RuntimeError) as caught:
                    gateway.execute(
                        call(name, **({"query": "evidence"} if name == "web.search" else {}))
                    )
                assert caught.value is signal
                assert len(children) == 1 and children[0].returncode == 0
                store = SQLiteWebResourceStore(
                    tmp_path / ".zebra-agent" / "web_resources.sqlite", tmp_path / "cache"
                )
                with store._database.connect() as connection:
                    assert (
                        connection.execute("SELECT COUNT(*) FROM web_resource").fetchone()[0] == 0
                    )
            finally:
                gateway.close()


def test_native_protocol_output_cap_is_failure_not_empty_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children = observe_children(monkeypatch)
    with native_connect_proxy(monkeypatch) as target:
        with native_tls_source(tmp_path, monkeypatch, "normal", on_listen=target.append) as (
            requests,
            _,
            _,
            _,
            _,
        ):
            with pytest.raises(WebGatewayError):
                _native_network_call(
                    "search_json",
                    "https://source.example/search",
                    lambda: None,
                    timeout=2,
                    use_system_proxy=True,
                    max_output_bytes=16,
                )
            assert len(requests) == 1
            assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("primary_type", [TimeoutError, asyncio.CancelledError])
@pytest.mark.parametrize("fault_mode", ["before_group_kill", "after_each_cleanup"])
@pytest.mark.skipif(os.name != "posix", reason="real group-kill cleanup probe is POSIX")
def test_cleanup_cancellation_preserves_primary_and_bounds_real_child_reap(
    monkeypatch: pytest.MonkeyPatch,
    primary_type: type[BaseException],
    fault_mode: str,
) -> None:
    import agent_runtime.web_gateway as gateway

    primary = primary_type("original Task failure")
    secondary = asyncio.CancelledError("secondary cleanup cancellation")
    original_spawn = subprocess.Popen
    original_group_kill = os.killpg
    children: list[subprocess.Popen[bytes]] = []
    steps: list[str] = []
    wait_timeouts: list[float | None] = []
    cleanup_entered = Event()
    cleanup_started: list[float] = []

    class CancelingPipe:
        def __init__(self, pipe, label):
            self.pipe, self.label = pipe, label

        def __getattr__(self, name):
            return getattr(self.pipe, name)

        def close(self):
            steps.append(self.label)
            self.pipe.close()
            if fault_mode == "after_each_cleanup":
                raise secondary

    def spawn(*args, **kwargs):
        child = original_spawn([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(child)
        original_kill, original_wait = child.kill, child.wait

        def kill():
            steps.append("process kill")
            original_kill()
            if fault_mode == "after_each_cleanup":
                raise secondary

        def wait(timeout=None):
            steps.append("reap")
            wait_timeouts.append(timeout)
            result = original_wait(timeout=timeout)
            if fault_mode == "after_each_cleanup":
                raise secondary
            return result

        child.kill, child.wait = kill, wait
        child.stdin = CancelingPipe(child.stdin, "stdin close")
        child.stdout = CancelingPipe(child.stdout, "stdout close")
        return child

    def check():
        if children:
            raise primary

    def terminate(child):
        cleanup_started.append(monotonic())
        cleanup_entered.set()
        steps.append("group kill")
        if fault_mode == "after_each_cleanup":
            original_group_kill(child.pid, signal.SIGKILL)
        raise secondary

    def group_kill(pid, sig):
        steps.append("raw group kill")
        try:
            original_group_kill(pid, sig)
        except ProcessLookupError:
            pass
        if fault_mode == "after_each_cleanup":
            raise secondary

    monkeypatch.setattr(gateway.subprocess, "Popen", spawn)
    monkeypatch.setattr(gateway, "_terminate_process_tree", terminate)
    monkeypatch.setattr(gateway.os, "killpg", group_kill)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_native_network_call, "resolve", "example.com", check, timeout=0.1)
        try:
            assert cleanup_entered.wait(2)
            with pytest.raises(primary_type) as caught:
                future.result(timeout=1)
            assert caught.value is primary
            assert monotonic() - cleanup_started[0] < 1
            assert steps == [
                "group kill",
                "raw group kill",
                "process kill",
                "stdin close",
                "stdout close",
                "reap",
            ]
            assert wait_timeouts and all(
                value is not None and 0 < value <= 0.5 for value in wait_timeouts
            )
            assert children[0].poll() is not None
            with pytest.raises(ChildProcessError):
                os.waitpid(children[0].pid, os.WNOHANG)
            assert children[0].stdin.closed and children[0].stdout.closed
            expected_notes = 6 if fault_mode == "after_each_cleanup" else 1
            assert len(primary.__notes__) == expected_notes
        finally:
            for child in children:
                if child.poll() is None:
                    original_group_kill(child.pid, signal.SIGKILL)
            try:
                future.result(timeout=2)
            except BaseException:
                pass
            for child in children:
                # Test-only failsafe also makes the old hanging implementation finish.
                original_spawn.wait(child, timeout=2)
                child.stdin.pipe.close()
                child.stdout.pipe.close()


def test_secondary_group_cancel_still_closes_real_tls_socket_and_reaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_group_kill(child):
        raise asyncio.CancelledError("secondary group-kill cancellation")

    monkeypatch.setattr("agent_runtime.web_gateway._terminate_process_tree", fail_group_kill)
    test_outer_cancel_stops_native_tls_read_and_reaps_before_return(
        tmp_path, monkeypatch, False, "web.fetch", asyncio.CancelledError
    )


@pytest.mark.skipif(os.name != "posix", reason="native process-group descendants are POSIX")
def test_group_kill_fallback_closes_descendant_socket_after_helper_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_runtime.web_gateway as gateway

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(2)
    entered, closed = Event(), Event()
    descendants: list[int] = []
    children: list[subprocess.Popen[bytes]] = []
    original_spawn = subprocess.Popen
    primary = asyncio.CancelledError("original Task cancellation with browser descendants")
    descendant_script = (
        "import os,socket; "
        f"s=socket.create_connection(('127.0.0.1',{listener.getsockname()[1]})); "
        "s.sendall(str(os.getpid()).encode()); s.recv(1)"
    )
    parent_script = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant_script!r}]); time.sleep(30)"
    )

    def peer():
        client, _ = listener.accept()
        with client:
            client.settimeout(2)
            descendants.append(int(client.recv(128)))
            entered.set()
            if client.recv(1) == b"":
                closed.set()

    def spawn(*args, **kwargs):
        child = original_spawn([sys.executable, "-c", parent_script], **kwargs)
        children.append(child)
        return child

    def check():
        if entered.is_set():
            raise primary

    def fail_group_kill(child):
        raise asyncio.CancelledError("helper canceled before the group KILL")

    thread = Thread(target=peer)
    thread.start()
    monkeypatch.setattr(gateway.subprocess, "Popen", spawn)
    monkeypatch.setattr(gateway, "_terminate_process_tree", fail_group_kill)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _native_network_call, "resolve", "example.com", check, timeout=2
            )
            try:
                assert entered.wait(2)
                with pytest.raises(asyncio.CancelledError) as caught:
                    future.result(timeout=1)
                assert caught.value is primary and descendants
                assert closed.wait(0.5), (
                    "the real descendant socket must close before fixture cleanup"
                )
                assert children[0].poll() is not None
                with pytest.raises(ChildProcessError):
                    os.waitpid(children[0].pid, os.WNOHANG)
                assert children[0].stdin.closed and children[0].stdout.closed
            finally:
                for child in children:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                try:
                    future.result(timeout=2)
                except BaseException:
                    pass
                for child in children:
                    child.wait(timeout=2)
    finally:
        listener.close()
        thread.join(2)
        assert not thread.is_alive()
