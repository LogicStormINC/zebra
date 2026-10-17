"""Bounded execution-scoped native children; only child-local DoH sockets persist."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from collections.abc import Callable
from threading import BoundedSemaphore, RLock
from time import monotonic
from typing import Any

from agent_tools.web_gateway import WebGatewayError

from agent_runtime.public_egress import Endpoint, validate_endpoint


class DohNetworkScope:
    def __init__(
        self, check: Callable[[], None], *, egress_endpoint: Endpoint | None = None,
    ) -> None:
        self._egress_endpoint = validate_endpoint(egress_endpoint)
        self._check = check
        self._lock = RLock()
        self._slots = BoundedSemaphore(2)
        self._idle: list[tuple[subprocess.Popen[bytes], float]] = []
        self._children: set[subprocess.Popen[bytes]] = set()
        self._closed = False

    def __call__(self) -> None:
        self._check()
        if self._closed:
            raise WebGatewayError("native network scope is closed")

    def _retire(self, child: subprocess.Popen[bytes]) -> None:
        from agent_runtime.web_gateway import _cleanup_network_child

        with self._lock:
            if child not in self._children:
                return
            primary = WebGatewayError("native network scope cleanup failed")
            _cleanup_network_child(child, primary)
            self._children.discard(child)

    def call(
        self,
        operation: str,
        arguments: object,
        *,
        timeout: float,
        use_system_proxy: bool,
        max_output_bytes: int,
        trusted_search_endpoint: str | None,
    ) -> object:
        deadline = monotonic() + timeout
        while True:
            self()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise WebGatewayError("native network request deadline exceeded")
            if self._slots.acquire(timeout=min(0.05, remaining)):
                break
        try:
            return self._exchange(
                operation,
                arguments,
                timeout=deadline - monotonic(),
                use_system_proxy=use_system_proxy,
                max_output_bytes=max_output_bytes,
                trusted_search_endpoint=trusted_search_endpoint,
            )
        finally:
            self._slots.release()

    def _exchange(
        self,
        operation: str,
        arguments: object,
        *,
        timeout: float,
        use_system_proxy: bool,
        max_output_bytes: int,
        trusted_search_endpoint: str | None,
    ) -> object:
        self()
        deadline = monotonic() + timeout
        stale: list[subprocess.Popen[bytes]] = []
        with self._lock:
            if self._closed:
                raise WebGatewayError("native network scope is closed")
            while self._idle and (
                monotonic() - self._idle[0][1] > 15 or self._idle[0][0].poll() is not None
            ):
                stale.append(self._idle.pop(0)[0])
            for old in stale:
                self._retire(old)
            child = self._idle.pop()[0] if self._idle else None
            # ponytail: at most two exclusive children per execution; queued callers
            # keep checking live authority within their original request deadline.
            if child is None and len(self._children) >= 2:
                raise WebGatewayError("native network scope capacity exhausted")
            if child is None:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "from agent_runtime.native_network_scope import network_child; "
                        "network_child()",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    bufsize=0,
                    env={**os.environ, "_ZEBRA_NATIVE_EGRESS": json.dumps(self._egress_endpoint)},
                )
                self._children.add(child)
        good = False
        try:
            data = (
                json.dumps(
                    (
                        operation,
                        arguments,
                        use_system_proxy,
                        max_output_bytes,
                        trusted_search_endpoint,
                    )
                ).encode()
                + b"\n"
            )
            if len(data) > 65_536:
                raise WebGatewayError("native network request exceeds protocol bound")
            assert child.stdin is not None and child.stdout is not None
            output = bytearray()
            with selectors.DefaultSelector() as selector:
                os.set_blocking(child.stdin.fileno(), False)
                os.set_blocking(child.stdout.fileno(), False)
                selector.register(child.stdin, selectors.EVENT_WRITE)
                selector.register(child.stdout, selectors.EVENT_READ)
                sent = 0
                while True:
                    self()
                    if self._closed:
                        raise WebGatewayError("native network scope is closed")
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise WebGatewayError("native network request deadline exceeded")
                    for key, _ in selector.select(min(0.05, remaining)):
                        if key.fileobj is child.stdin:
                            sent += os.write(child.stdin.fileno(), data[sent:])
                            if sent == len(data):
                                selector.unregister(child.stdin)
                        else:
                            chunk = os.read(child.stdout.fileno(), 65_536)
                            if not chunk:
                                raise WebGatewayError("native network child ended unexpectedly")
                            output.extend(chunk)
                            if len(output) > max_output_bytes + 1:
                                raise WebGatewayError("native network response exceeds bound")
                    if b"\n" in output:
                        if output[-1:] != b"\n" or output.count(b"\n") != 1:
                            raise WebGatewayError("invalid native network response framing")
                        self()  # Never publish a completed response after authority revocation.
                        result = json.loads(output)
                        if "error" in result:
                            raise WebGatewayError(
                                result["error"],
                                reason=result["reason"],
                                metadata=result.get("metadata"),
                            )
                        good = True
                        return result["result"]
        finally:
            if good:
                with self._lock:
                    if not self._closed:
                        self._idle.append((child, monotonic()))
                        child = None
            if child is not None:
                self._retire(child)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            children = tuple(self._children)
            self._idle.clear()
        for child in children:
            self._retire(child)


def network_child() -> None:
    from agent_runtime.doh_transport import DohTransport, current_doh_transport
    from agent_runtime.public_egress import current_public_egress
    from agent_runtime.web_gateway import _execute_network_operation

    endpoint = validate_endpoint(json.loads(os.environ.get("_ZEBRA_NATIVE_EGRESS", "null")))
    egress_token = current_public_egress.set(endpoint)
    transport = DohTransport()
    token = current_doh_transport.set(transport)
    try:
        while True:
            line = sys.stdin.buffer.readline(65_537)
            if not line:
                return
            if len(line) > 65_536 or not line.endswith(b"\n"):
                return
            operation, arguments, proxy, maximum, search_endpoint = json.loads(line)
            if operation not in {"fetch", "search", "search_json", "resolve"}:
                return
            result: dict[str, Any]
            try:
                value = _execute_network_operation(operation, arguments, proxy, search_endpoint)
                result = {"result": value}
                output = json.dumps(result).encode()
                if len(output) > maximum:
                    raise WebGatewayError(
                        "native network output exceeds its byte bound", reason="response_too_large"
                    )
            except WebGatewayError as exc:
                transport.close()
                output = json.dumps(
                    {"error": str(exc), "reason": exc.reason, "metadata": exc.metadata}
                ).encode()
            if len(output) > maximum:
                return
            sys.stdout.buffer.write(output + b"\n")
            sys.stdout.buffer.flush()
    finally:
        current_doh_transport.reset(token)
        current_public_egress.reset(egress_token)
        transport.close()
