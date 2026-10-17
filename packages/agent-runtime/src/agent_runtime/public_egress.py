"""Explicit child-scoped public-IP egress; TLS and DNS admission stay with callers."""

from __future__ import annotations

import errno
import ipaddress
import math
import socket
from contextvars import ContextVar
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_runtime.public_dns import AddressInfo

Endpoint = tuple[str, int]
current_public_egress: ContextVar[Endpoint | None] = ContextVar("public_egress", default=None)


def validate_endpoint(value: object) -> Endpoint | None:
    if value is None:
        return None
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError("egress endpoint must be [numeric IP, port]")
    host, port = value
    if not isinstance(host, str) or type(port) is not int or not 0 < port < 65536:
        raise ValueError("invalid egress endpoint")
    ip = ipaddress.ip_address(host)
    if ip.is_unspecified or ip.is_multicast or getattr(ip, "scope_id", None):
        raise ValueError("invalid egress endpoint IP")
    return str(ip), port


def _remaining(sock: socket.socket, deadline: float) -> None:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("egress handshake deadline exceeded")
    sock.settimeout(remaining)


def _read(sock: socket.socket, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        _remaining(sock, deadline)
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("egress response truncated")
        data.extend(chunk)
    return bytes(data)


def _send(sock: socket.socket, data: bytes, deadline: float) -> None:
    _remaining(sock, deadline)
    sock.sendall(data)


def _greet(sock: socket.socket, deadline: float) -> None:
    _send(sock, b"\x05\x01\x00", deadline)
    if _read(sock, 2, deadline) != b"\x05\x00":
        raise OSError("egress authentication method rejected")


def probe_egress(endpoint: Endpoint, *, timeout: float = 3) -> None:
    """Startup-only remote TCP readiness to the fixed DoH service; no task data."""
    configured = validate_endpoint(endpoint)
    assert configured is not None
    token = current_public_egress.set(configured)
    try:
        connect_address(
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)), timeout=timeout
        ).close()
    finally:
        current_public_egress.reset(token)


def connect_address(
    address: AddressInfo,
    *,
    timeout: float | None,
    source_address: tuple[str, int] | None = None,
    public: bool = True,
) -> socket.socket:
    """Connect once to an admitted address; no hostname resolution, retries or fallback."""
    family, kind, protocol, _, target = address
    endpoint = current_public_egress.get() if public else None
    if endpoint is not None:
        ip = ipaddress.ip_address(target[0])
        if not ip.is_global or ip.is_reserved or ip.is_multicast:
            raise OSError("egress target must be public")
        if timeout is None or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("controlled egress requires a finite request timeout")
        if type(target[1]) is not int or not 0 < target[1] < 65536:
            raise ValueError("invalid egress target port")
        deadline = monotonic() + timeout
        family, kind, protocol = (
            socket.AF_INET6 if ":" in endpoint[0] else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
        )
    connection = socket.socket(family, kind, protocol)
    try:
        connection.settimeout(timeout)
        if source_address is not None:
            connection.bind(source_address)
        connection.connect(endpoint if endpoint is not None else target)
        if endpoint is not None:
            _greet(connection, deadline)
            atyp = b"\x01" if ip.version == 4 else b"\x04"
            _send(
                connection,
                b"\x05\x01\x00" + atyp + ip.packed + int(target[1]).to_bytes(2, "big"),
                deadline,
            )
            reply = _read(connection, 4, deadline)
            if reply[:3] != b"\x05\x00\x00":
                raise OSError("egress CONNECT rejected")
            if reply[3] == 1:
                size = 4
            elif reply[3] == 4:
                size = 16
            elif reply[3] == 3:
                size = _read(connection, 1, deadline)[0]
                if size == 0:
                    raise OSError("egress bound address empty")
            else:
                raise OSError("egress address type rejected")
            _read(connection, size + 2, deadline)
            connection.settimeout(timeout)
        try:
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            if exc.errno != errno.ENOPROTOOPT:
                raise
        return connection
    except BaseException:
        connection.close()
        raise
