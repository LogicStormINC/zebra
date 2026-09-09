"""Direct MCP HTTPS sockets: validate DNS at connection time, then pin the IP."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.request


class PublicMcpHttpsConnection(http.client.HTTPSConnection):
    _tunnel_host: str | None
    _context: ssl.SSLContext
    source_address: tuple[str, int] | None

    def connect(self) -> None:
        if self._tunnel_host is not None:
            raise OSError("MCP proxy tunnels are unsupported")
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise OSError("MCP target resolves to a blocked address")
        # ponytail: use the first validated address, with no request replay or
        # second hostname resolution; multi-address fallback can be added pre-TLS.
        family, kind, protocol, _, address = addresses[0]
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(self.timeout)
            if self.source_address is not None:
                connection.bind(self.source_address)
            connection.connect(address)
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except BaseException:
            connection.close()
            raise


class PublicMcpHttpsHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(PublicMcpHttpsConnection, req)
