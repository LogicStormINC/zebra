"""Direct MCP HTTPS sockets: validate DNS at connection time, then pin the IP."""

from __future__ import annotations

import http.client
import ssl
import urllib.request
from collections.abc import Sequence

from agent_runtime.public_dns import AddressInfo, public_addresses
from agent_runtime.public_egress import connect_address


class PublicMcpHttpsConnection(http.client.HTTPSConnection):
    _tunnel_host: str | None
    _context: ssl.SSLContext
    _controlled_egress = True
    source_address: tuple[str, int] | None

    def resolve_addresses(self) -> Sequence[AddressInfo]:
        return public_addresses(self.host, self.port)

    def connect(self) -> None:
        if self._tunnel_host is not None:
            raise OSError("MCP proxy tunnels are unsupported")
        addresses = self.resolve_addresses()
        # ponytail: use the first validated address, with no request replay or
        # second hostname resolution; multi-address fallback can be added pre-TLS.
        connection = connect_address(
            addresses[0], timeout=self.timeout, source_address=self.source_address,
            public=self._controlled_egress,
        )
        try:
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except BaseException:
            connection.close()
            raise


class PublicMcpHttpsHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(PublicMcpHttpsConnection, req)
