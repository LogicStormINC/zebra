"""Read-only daemon/verified-TLS timing. Never submits Runs or invokes a model."""

import argparse
import hashlib
import http.client
import json
import os
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost", timeout=5)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(self.path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unix", help="Run on the daemon host using this Unix socket")
    parser.add_argument("--port", type=int, help="Verified bridge port; host stays DOCKER_HOST")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--connect-proxy", help="Explicit local HTTP CONNECT endpoint")
    args = parser.parse_args()
    if not 1 <= args.samples <= 20:
        parser.error("samples must be 1..20")
    if args.unix:

        def connection():
            return UnixConnection(args.unix)
    else:
        endpoint = urlsplit(os.environ["DOCKER_HOST"])
        root = Path(os.environ["DOCKER_CERT_PATH"])
        context = ssl.create_default_context(cafile=str(root / "ca.pem"))
        context.load_cert_chain(str(root / "cert.pem"), str(root / "key.pem"))

        def connection():
            if args.connect_proxy:
                proxy = urlsplit(args.connect_proxy)
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
                    parser.error("proxy must be a credential-free HTTP endpoint")
                client = http.client.HTTPSConnection(
                    proxy.hostname, proxy.port, context=context, timeout=5
                )
                client.set_tunnel(endpoint.hostname, args.port or endpoint.port)
                return client
            return http.client.HTTPSConnection(
                endpoint.hostname, args.port or endpoint.port, context=context, timeout=5
            )

    rows = []
    for mode in ("cold", "warm"):
        client = None
        try:
            for _ in range(args.samples):
                if client is None:
                    client = connection()
                started = time.monotonic()
                client.request("GET", "/info")
                response = client.getresponse()
                headers = time.monotonic()
                body = response.read(131_073)
                ended = time.monotonic()
                if response.status != 200 or len(body) > 131_072:
                    raise RuntimeError("invalid bounded daemon response")
                value = json.loads(body)
                identity = value.get("ID") if isinstance(value, dict) else None
                if not isinstance(identity, str) or not identity.strip():
                    raise RuntimeError("missing daemon identity")
                rows.append(
                    {
                        "mode": mode,
                        "headers_ms": round((headers - started) * 1000, 3),
                        "body_ms": round((ended - headers) * 1000, 3),
                        "total_ms": round((ended - started) * 1000, 3),
                        "bytes": len(body),
                        "identity_sha256": hashlib.sha256(identity.strip().encode()).hexdigest(),
                    }
                )
                if mode == "cold":
                    client.close()
                    client = None
        finally:
            if client is not None:
                client.close()
    if len({row["identity_sha256"] for row in rows}) != 1:
        raise RuntimeError("daemon identity changed during measurement")
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
