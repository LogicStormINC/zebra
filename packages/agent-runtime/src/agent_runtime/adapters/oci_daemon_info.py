"""Fresh daemon identity reads over one verified mTLS connection; no result cache."""

import json
import ssl
from hashlib import sha256
from http.client import HTTPSConnection, RemoteDisconnected
from pathlib import Path
from socket import SHUT_RDWR, socket
from threading import Lock, Timer
from time import monotonic
from typing import cast
from urllib.parse import urlsplit
from weakref import finalize

from agent_core.ports.runtime import RuntimeCapabilityError


class DockerDaemonInfo:
    def __init__(
        self, host: str, port: int, certificate_root: str, *, connect_proxy: str = ""
    ) -> None:
        root = Path(certificate_root)
        paths = [root / name for name in ("ca.pem", "cert.pem", "key.pem")]
        self._files = {path: sha256(path.read_bytes()).digest() for path in paths}
        context = ssl.create_default_context(cafile=str(paths[0]))
        context.load_cert_chain(str(paths[1]), str(paths[2]))
        if connect_proxy:
            proxy = urlsplit(connect_proxy)
            if (
                proxy.scheme != "http"
                or not proxy.hostname
                or not proxy.port
                or proxy.username
                or proxy.password
                or proxy.path not in ("", "/")
                or proxy.query
                or proxy.fragment
            ):
                raise RuntimeCapabilityError(
                    "daemon info CONNECT proxy requires a credential-free HTTP endpoint"
                )
            self._connection = HTTPSConnection(
                proxy.hostname, proxy.port, context=context, timeout=10
            )
            # stdlib verifies the tunnel target's certificate; TLS remains end-to-end.
            self._connection.set_tunnel(host, port)
        else:
            self._connection = HTTPSConnection(host, port, context=context, timeout=10)
        self._lock = Lock()
        self._request_socket: socket | None = None
        # Also release an unused/preflight transport when its engine leaves scope.
        self._finalizer = finalize(self, self._connection.close)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def identity(self) -> str:
        try:
            return str(self.read()["ID"]).strip()
        except TimeoutError:
            raise RuntimeCapabilityError("cloud Docker daemon identity is unavailable") from None

    def read(self, *, timeout: float = 10) -> dict[str, object]:
        deadline = monotonic() + timeout
        if not self._lock.acquire(timeout=timeout):
            raise TimeoutError("cloud Docker daemon identity read timed out")
        timer = Timer(max(0, deadline - monotonic()), self._abort)
        timer.daemon = True
        timer.start()
        try:
            if any(
                sha256(path.read_bytes()).digest() != digest for path, digest in self._files.items()
            ):
                raise RuntimeCapabilityError("runtime engine TLS identity changed after pinning")
            for attempt in range(2):
                try:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    self._connection.timeout = remaining
                    if self._connection.sock is not None:
                        self._connection.sock.settimeout(remaining)
                    self._connection.request("GET", "/info")
                    self._request_socket = self._connection.sock
                    response = self._connection.getresponse()
                    body = response.read(131_073)
                    if monotonic() >= deadline:
                        raise TimeoutError
                    if response.status != 200 or len(body) > 131_072:
                        raise ValueError("invalid daemon response")
                    break
                except (RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                    self._connection.close()
                    self._request_socket = None
                    if attempt or monotonic() >= deadline:
                        raise
                    # Reconnect only this read; the mutating command has not run yet.
            value = json.loads(body)
            identity = value.get("ID") if isinstance(value, dict) else None
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError("missing daemon identity")
            return cast(dict[str, object], value)
        except TimeoutError:
            self._connection.close()
            raise
        except RuntimeCapabilityError:
            self._connection.close()
            raise
        except Exception:
            self._connection.close()
            if monotonic() >= deadline:
                raise TimeoutError("cloud Docker daemon read timed out") from None
            # No command retry or CLI fallback after a failed identity read.
            raise RuntimeCapabilityError("cloud Docker daemon identity is unavailable") from None
        finally:
            timer.cancel()
            timer.join()
            self._request_socket = None
            self._lock.release()

    def _abort(self) -> None:
        sock = self._request_socket or self._connection.sock
        if sock is not None:
            try:
                sock.shutdown(SHUT_RDWR)
            except OSError:
                pass
