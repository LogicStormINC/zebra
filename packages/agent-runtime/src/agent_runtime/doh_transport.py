"""Execution-child-local DoH connection reuse; DNS answers are never cached."""

from __future__ import annotations

import http.client
import ssl
import urllib.parse
import urllib.request
from contextvars import ContextVar
from time import monotonic


class DohTransport:
    """Exclusive child use only; reject redirects and retire failed/idle sockets."""

    def __init__(self) -> None:
        self._connection: http.client.HTTPSConnection | None = None
        self._used_at = 0.0

    def open(self, request: urllib.request.Request, timeout: float) -> http.client.HTTPResponse:
        parts = urllib.parse.urlsplit(request.full_url)
        if (parts.scheme, parts.netloc, parts.path) != ("https", "1.1.1.1", "/dns-query"):
            raise ValueError("unexpected DoH endpoint")
        if request.get_method() != "GET":
            raise ValueError("unexpected DoH method")
        if monotonic() - self._used_at > 15:
            self.close()
        if self._connection is None:
            self._connection = http.client.HTTPSConnection(
                "1.1.1.1", timeout=timeout, context=ssl.create_default_context()
            )
        try:
            self._connection.timeout = timeout
            if self._connection.sock is not None:
                self._connection.sock.settimeout(timeout)
            self._connection.request(
                "GET", parts.path + "?" + parts.query, headers={"Accept": "application/dns-json"}
            )
            response = self._connection.getresponse()
            self._used_at = monotonic()
            return response
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


# Child scope explicitly set/reset by the bounded native protocol, never a global cache.
current_doh_transport: ContextVar[DohTransport | None] = ContextVar("doh_transport", default=None)
