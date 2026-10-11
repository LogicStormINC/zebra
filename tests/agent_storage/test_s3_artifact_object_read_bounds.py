"""Actual signed S3 HTTP reads, not timed-out mock/executor acceptance."""

import asyncio
import os
import socket
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import copy_context
from dataclasses import dataclass, field
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Barrier, Event, Thread
from time import monotonic
from uuid import uuid4

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectIntegrityError,
    ArtifactObjectUnavailableError,
)
from agent_core.domain.identifiers import ArtifactId
from agent_storage import artifact_object_reads as reads
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.task_io import task_io_deadline
from botocore.config import Config
from botocore.session import Session

PAYLOAD = b"x" * 80


@dataclass
class NativeProbe:
    entered: Event = field(default_factory=Event)
    disconnected: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    requests: list[tuple[str, str, str | None]] = field(default_factory=list)


@pytest.fixture
def children(monkeypatch):
    captured = []
    spawn = subprocess.Popen

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        captured.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", record)
    yield captured
    for child in captured:
        assert child.poll() is not None, "immutable read left a live child"
        with pytest.raises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
        assert child.stdin.closed
        assert "scratch-secret" not in str(child.args)


@contextmanager
def native_server(
    mode: str, object_payload: bytes = PAYLOAD
) -> Iterator[tuple[S3ArtifactObjectStore, NativeProbe]]:
    probe = NativeProbe()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        def do_HEAD(self) -> None:
            self.respond()

        def do_GET(self) -> None:
            self.respond()

        def respond(self) -> None:
            probe.requests.append((self.command, self.path, self.headers.get("Range")))
            assert "AWS4-HMAC-SHA256" in self.headers["Authorization"]
            if mode == "blocked_head":
                probe.entered.set()
                self.wait_for_close()
                return
            error = self.command == "GET" and mode.startswith("error")
            redirect = self.command == "GET" and mode == "redirect"
            ranged = self.headers.get("Range") is not None
            payload = object_payload[2:6] if ranged else object_payload
            if error:
                payload = b"<Error><Code>SlowDown</Code></Error>"
            self.send_response(301 if redirect else 503 if error else 206 if ranged else 200)
            if redirect:
                self.send_header("x-amz-bucket-region", "eu-west-1")
                payload = b"<Error><Code>PermanentRedirect</Code></Error>"
            overlong = self.command == "GET" and mode in {"overlong", "error_overlong"}
            oversize = self.command == "GET" and mode in {"oversize", "error_oversize"}
            if overlong:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header(
                    "Content-Length", str(65_537 if error and oversize else len(payload) + oversize)
                )
            self.send_header("x-amz-version-id", "v2" if mode == "wrong_version" else "v1")
            if ranged:
                self.send_header(
                    "Content-Range",
                    f"bytes 2-5/{len(object_payload) + (mode == 'wrong_range')}",
                )
            self.send_header("Last-Modified", "Wed, 29 Jul 2026 00:00:00 GMT")
            self.send_header("x-amz-meta-zebra-sha256", sha256(object_payload).hexdigest())
            self.send_header("x-amz-meta-zebra-size-bytes", str(len(object_payload)))
            if self.command == "GET" and mode == "oversize_header":
                self.send_header("X-Unbounded", "x" * 10_000)
            self.end_headers()
            if self.command == "HEAD":
                return
            self.wfile.flush()
            probe.entered.set()
            if mode in {"blocked_get", "oversize", "error_oversize"}:
                self.wait_for_close()
                return
            try:
                if overlong:
                    payload = b"x" * (65_537 if error else len(payload) + 1)
                    self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n")
                    self.wfile.flush()
                    return
                if mode != "drip":
                    self.wfile.write(payload)
                    self.wfile.flush()
                    return
                for byte in payload:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    if probe.release.wait(0.025):
                        return
            except (BrokenPipeError, ConnectionResetError):
                probe.disconnected.set()

        def wait_for_close(self) -> None:
            self.connection.settimeout(3)
            try:
                assert self.connection.recv(1) == b""
                probe.disconnected.set()
            except ConnectionResetError:
                probe.disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    client = Session().create_client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{server.server_port}",
        aws_access_key_id="scratch-key",
        aws_secret_access_key="scratch-secret",
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=1.8,
            read_timeout=1.8,
            retries={"total_max_attempts": 1},
        ),
    )
    try:
        yield S3ArtifactObjectStore(client, bucket="scratch"), probe
    finally:
        probe.release.set()
        client.close()
        server.shutdown()
        thread.join(1)
        server.server_close()


def expectation() -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation(
        deployment_namespace="scratch",
        artifact_id=ArtifactId(uuid4()),
        sha256=sha256(PAYLOAD).hexdigest(),
        size_bytes=len(PAYLOAD),
    )


@pytest.mark.parametrize("mode", ["blocked_head", "drip"])
def test_native_s3_read_honors_actual_cumulative_deadline(mode: str, children) -> None:
    with native_server(mode) as (store, probe):
        started = monotonic()
        with pytest.raises((TimeoutError, ArtifactObjectUnavailableError)):
            with task_io_deadline(started + 0.7):
                store.verify(expectation()) if mode == "blocked_head" else (
                    store.read_verified(expectation())
                )
        assert probe.entered.is_set()
        assert monotonic() - started < 1.0
        assert probe.disconnected.wait(0.5)
        assert len(children) == (1 if mode == "blocked_head" else 2)


@pytest.mark.parametrize("mode", ["blocked_head", "blocked_get", "drip"])
def test_explicit_cancel_kills_and_reaps_actual_io(mode, children):
    with native_server(mode) as (store, probe):
        errors = []
        with (
            pytest.raises(asyncio.CancelledError),
            reads.artifact_read_scope(deadline=monotonic() + 2) as scope,
        ):

            def run():
                try:
                    store.verify(expectation()) if mode == "blocked_head" else (
                        store.read_verified(expectation())
                    )
                except BaseException as error:
                    errors.append(error)

            worker = Thread(target=copy_context().run, args=(run,))
            worker.start()
            assert probe.entered.wait(1)
            scope.cancel()
            worker.join(0.5)
            assert not worker.is_alive(), "cancel left the parent read thread running"
            assert len(errors) == 1 and isinstance(errors[0], asyncio.CancelledError)
            assert probe.disconnected.wait(0.5)
            assert children and all(child.poll() is not None for child in children)


@pytest.mark.parametrize("mode", ["normal", "wrong_range", "wrong_version"])
def test_native_range_preserves_exact_version_and_content_range(mode, children):
    with native_server(mode) as (store, probe):
        if mode == "normal":
            assert store.read_version_range_verified(expectation(), "v1", 2, 5) == PAYLOAD[2:6]
        else:
            with pytest.raises(ArtifactObjectIntegrityError):
                store.read_version_range_verified(expectation(), "v1", 2, 5)
        assert len(probe.requests) in {1, 2}
        if len(probe.requests) == 2:
            assert probe.requests[-1][2] == "bytes=2-5"
            assert "versionId=v1" in probe.requests[-1][1]


@pytest.mark.parametrize(
    "mode", ["oversize", "overlong", "error_oversize", "error_overlong", "oversize_header"]
)
def test_native_raw_bounds_fail_before_parser_allocation(mode, children, monkeypatch):
    parsed = []
    response = reads.AWSResponse

    def record(*args, **kwargs):
        parsed.append(True)
        return response(*args, **kwargs)

    monkeypatch.setattr(reads, "AWSResponse", record)
    with native_server(mode) as (store, probe):
        with pytest.raises(ArtifactObjectUnavailableError):
            store.read_version_verified(expectation(), "v1")
        assert parsed == [], "oversize response reached the native parser"
        assert len(probe.requests) == len(children) == 1
        if mode in {"oversize", "error_oversize"}:
            assert probe.disconnected.wait(0.5), "declared oversize attempted body read"


@pytest.mark.parametrize("mode", ["error", "redirect"])
def test_native_errors_and_region_redirect_never_retry(mode, children):
    with native_server(mode) as (store, probe):
        with pytest.raises(ArtifactObjectUnavailableError):
            store.read_version_verified(expectation(), "v1")
        assert len(probe.requests) == len(children) == 1


def test_stalled_native_dns_is_killed_and_reaped(children, monkeypatch):
    script = reads._READ_SCRIPT.replace(
        "data=json.load(sys.stdin)",
        "data=json.load(sys.stdin)\nimport socket,time\n"
        "socket.getaddrinfo=lambda *a,**k: time.sleep(10)",
    )
    monkeypatch.setattr(reads, "_READ_SCRIPT", script)
    with native_server("normal") as (store, probe):
        started = monotonic()
        with pytest.raises(TimeoutError):
            with reads.artifact_read_scope(deadline=started + 0.3):
                store.verify(expectation())
        assert monotonic() - started < 0.6
        assert len(children) == 1 and probe.requests == []


@contextmanager
def native_tls_server() -> Iterator[tuple[S3ArtifactObjectStore, NativeProbe]]:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(0.05)
        probe = NativeProbe()

        def peer():
            while not probe.release.is_set():
                try:
                    connection, _ = server.accept()
                except (TimeoutError, ConnectionAbortedError):
                    # A child killed before accept need not leave an accepted socket.
                    continue
                with connection:
                    connection.settimeout(2)
                    try:
                        while connection.recv(65536):
                            probe.entered.set()  # Actual TLS ClientHello reached the peer.
                        probe.disconnected.set()
                    except ConnectionResetError:
                        probe.disconnected.set()
                return

        worker = Thread(target=peer)
        client = Session().create_client(
            "s3",
            endpoint_url=f"https://127.0.0.1:{server.getsockname()[1]}",
            aws_access_key_id="scratch-key",
            aws_secret_access_key="scratch-secret",
            region_name="us-east-1",
            verify=False,
            config=Config(signature_version="s3v4", retries={"total_max_attempts": 1}),
        )
        store = S3ArtifactObjectStore(client, bucket="scratch")
        worker.start()
        try:
            yield store, probe
        finally:
            probe.release.set()
            worker.join(0.5)
            client.close()
            assert not worker.is_alive(), "TLS fixture left an accept/socket thread running"


def test_tls_deadline_closes_or_aborts_socket_and_reaps_child(children):
    with native_tls_server() as (store, probe):
        started = monotonic()
        with pytest.raises(TimeoutError):
            with reads.artifact_read_scope(deadline=started + 0.3):
                store.verify(expectation())
        assert monotonic() - started < 0.7
        assert len(children) <= 1
        if probe.entered.is_set():
            assert probe.disconnected.wait(0.5)
        # A pre-connect deadline is valid, but is not handshake cancellation proof.


def test_cancel_after_actual_tls_client_hello_closes_socket_and_reaps_child(children):
    with native_tls_server() as (store, probe):
        errors = []
        with (
            pytest.raises(asyncio.CancelledError),
            reads.artifact_read_scope(deadline=monotonic() + 2) as scope,
        ):

            def run():
                try:
                    store.verify(expectation())
                except BaseException as error:
                    errors.append(error)

            worker = Thread(target=copy_context().run, args=(run,))
            worker.start()
            assert probe.entered.wait(1.5), "fixture did not reach a real TLS handshake"
            started = monotonic()
            scope.cancel()
            worker.join(0.5)
            assert monotonic() - started < 0.7
            assert not worker.is_alive() and len(children) == 1
            assert len(errors) == 1 and isinstance(errors[0], asyncio.CancelledError)
            assert probe.disconnected.wait(0.5)


def test_range_budget_does_not_allocate_the_full_object(children):
    with native_server("normal") as (store, probe):
        with reads.artifact_read_scope(max_bytes=4):
            assert store.read_version_range_verified(expectation(), "v1", 2, 5) == PAYLOAD[2:6]
        assert len(children) == len(probe.requests) == 2
        with pytest.raises(ArtifactObjectUnavailableError), reads.artifact_read_scope(max_bytes=4):
            store.read_version_verified(expectation(), "v1")
        assert len(children) == len(probe.requests) == 2


@pytest.mark.parametrize("constraint", ["bytes", "deadline"])
def test_nested_scope_cannot_discard_a_tighter_constraint(constraint, children):
    with native_server("blocked_head") as (store, probe):
        started = monotonic()
        with reads.artifact_read_scope(deadline=started + 2, max_bytes=128):
            with pytest.raises((TimeoutError, ArtifactObjectUnavailableError)):
                with reads.artifact_read_scope(
                    deadline=started + 0.3 if constraint == "deadline" else started + 2,
                    max_bytes=4 if constraint == "bytes" else 128,
                ):
                    store.verify(expectation()) if constraint == "deadline" else (
                        store.read_version_verified(expectation(), "v1")
                    )
        assert monotonic() - started < 0.7
        if constraint == "bytes":
            assert children == [] and probe.requests == []


def test_saturated_child_admission_shares_deadline_without_spawning(monkeypatch, children):
    from threading import BoundedSemaphore

    capacity = BoundedSemaphore(1)
    assert capacity.acquire()
    monkeypatch.setattr(reads, "_CHILDREN", capacity)
    with native_server("normal") as (store, probe):
        started = monotonic()
        with pytest.raises(TimeoutError), reads.artifact_read_scope(deadline=started + 0.15):
            store.verify(expectation())
        assert monotonic() - started < 0.4
        assert children == [] and probe.requests == []
    capacity.release()


def test_actual_eight_child_capacity_cancel_reaps_every_socket_and_process(monkeypatch, children):
    admitted, disconnected = Barrier(9), Barrier(9)
    errors, workers = [], []
    with native_server("blocked_head") as (store, probe):
        monkeypatch.setattr(probe.entered, "set", lambda: admitted.wait(timeout=1.5))
        monkeypatch.setattr(probe.disconnected, "set", lambda: disconnected.wait(timeout=1))
        with pytest.raises(asyncio.CancelledError), reads.artifact_read_scope() as scope:

            def run():
                try:
                    store.verify(expectation())
                except BaseException as error:
                    errors.append(error)

            try:
                for _ in range(8):
                    worker = Thread(target=copy_context().run, args=(run,))
                    workers.append(worker)
                    worker.start()
                admitted.wait(timeout=1.5)
                assert len(children) == len(probe.requests) == 8
                with (
                    pytest.raises(TimeoutError),
                    reads.artifact_read_scope(deadline=monotonic() + 0.15),
                ):
                    store.verify(expectation())
                assert len(children) == len(probe.requests) == 8
                started = monotonic()
                scope.cancel()
                for worker in workers:
                    worker.join(max(0, started + 0.7 - monotonic()))
                disconnected.wait(timeout=0.5)
                assert monotonic() - started < 0.7
                assert not any(worker.is_alive() for worker in workers)
                assert len(errors) == 8 and all(
                    isinstance(error, asyncio.CancelledError) for error in errors
                )
                assert all(child.poll() is not None for child in children)
            finally:
                scope.cancel()
                for worker in workers:
                    worker.join(2)


@pytest.mark.parametrize("has_primary", [False, True])
def test_scope_cancel_attempts_every_child_and_preserves_primary(
    monkeypatch, children, has_primary
):
    entered, disconnected = Barrier(3), Barrier(3)
    primary = asyncio.CancelledError("original cancellation")
    secondary = asyncio.CancelledError("secondary kill cleanup")
    errors, workers, killed = [], [], []
    disconnected_once = False
    with native_server("blocked_head") as (store, probe):
        monkeypatch.setattr(probe.entered, "set", lambda: entered.wait(timeout=1.5))
        monkeypatch.setattr(probe.disconnected, "set", lambda: disconnected.wait(timeout=1))
        with pytest.raises(asyncio.CancelledError), reads.artifact_read_scope() as scope:

            def run():
                try:
                    store.verify(expectation())
                except BaseException as error:
                    errors.append(error)

            try:
                for _ in range(2):
                    worker = Thread(target=copy_context().run, args=(run,))
                    workers.append(worker)
                    worker.start()
                entered.wait(timeout=1.5)
                kill = type(children[0]).kill

                def failing_kill(child):
                    kill(child)
                    killed.append(child.pid)
                    raise secondary

                with monkeypatch.context() as fault:
                    fault.setattr(type(children[0]), "kill", failing_kill)
                    if has_primary:
                        try:
                            scope.cancel(primary)
                        except BaseException as error:
                            raise AssertionError(
                                "secondary cancellation escaped cleanup"
                            ) from error
                        assert len(primary.__notes__) == 2
                    else:
                        with pytest.raises(asyncio.CancelledError) as caught:
                            scope.cancel()
                        assert caught.value is secondary
                assert set(killed) == {child.pid for child in children}
                disconnected.wait(timeout=0.5)
                disconnected_once = True
                for worker in workers:
                    worker.join(0.5)
                assert not any(worker.is_alive() for worker in workers)
                assert len(errors) == 2 and all(
                    isinstance(error, asyncio.CancelledError) for error in errors
                )
            finally:
                scope.cancel()
                for worker in workers:
                    worker.join(2)
                if not disconnected_once:
                    disconnected.wait(timeout=1)
                store._read_client.close()


@pytest.mark.parametrize("mode", ["normal", "blocked_head"])
def test_child_cleanup_attempts_close_and_reap_after_secondary_cancel(mode, monkeypatch, children):
    secondary = asyncio.CancelledError("secondary process cleanup")
    steps = []
    spawn = subprocess.Popen

    def start(*args, **kwargs):
        child = spawn(*args, **kwargs)
        stdin, kill, wait = child.stdin, child.kill, child.wait
        closes = 0

        class Stdin:
            def __getattr__(self, name):
                return getattr(stdin, name)

            def close(self):
                nonlocal closes
                closes += 1
                stdin.close()
                if closes > 1:
                    steps.append("close")
                    raise secondary

        def failing_kill():
            kill()
            steps.append("kill")
            raise secondary

        def failing_wait(*args, **kwargs):
            final = bool(steps)
            if final:
                steps.append("wait")
            result = wait(*args, **kwargs)
            if final:
                raise secondary
            return result

        child.stdin = Stdin()
        child.kill, child.wait = failing_kill, failing_wait
        return child

    monkeypatch.setattr(subprocess, "Popen", start)
    with native_server(mode) as (store, probe):
        try:
            with pytest.raises(BaseException) as caught:
                with reads.artifact_read_scope(deadline=monotonic() + 0.7):
                    store.verify(expectation())
            if mode == "normal":
                assert caught.value is secondary  # No primary: never swallow cleanup failure.
                assert steps == ["close", "wait"]
            else:
                assert isinstance(caught.value, TimeoutError)
                assert steps == ["kill", "close", "wait"]
                assert len(caught.value.__notes__) == 3
                assert probe.disconnected.wait(0.5)
            assert children[0].poll() is not None
        finally:
            for child in children:
                if child.poll() is None:
                    type(child).kill(child)
                type(child).wait(child, timeout=1)
            store._read_client.close()
