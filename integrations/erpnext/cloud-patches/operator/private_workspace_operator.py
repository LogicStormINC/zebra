"""Root-owned ERP-only quota allocator. No browser paths or commands are accepted."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import signal
import socket
import socketserver
import stat
import struct
import subprocess as subprocess
import time
from pathlib import Path

from private_workspace_allocator import (
    BYTE_LIMIT as BYTE_LIMIT,
)
from private_workspace_allocator import (
    DEADLINE as DEADLINE,
)
from private_workspace_allocator import (
    FLOOR as FLOOR,
)
from private_workspace_allocator import (
    LIMIT as LIMIT,
)
from private_workspace_allocator import (
    MAX_BODY as MAX_BODY,
)
from private_workspace_allocator import (
    REQUEST_SECONDS as REQUEST_SECONDS,
)
from private_workspace_allocator import (
    ROOT as ROOT,
)
from private_workspace_allocator import (
    SIZE as SIZE,
)
from private_workspace_allocator import (
    STATE as STATE,
)
from private_workspace_allocator import (
    Allocator as Allocator,
)
from private_workspace_allocator import (
    canonical as canonical,
)
from private_workspace_allocator import (
    mount_evidence as mount_evidence,
)
from private_workspace_allocator import (
    remaining as remaining,
)
from private_workspace_allocator import (
    require_fresh as require_fresh,
)
from private_workspace_allocator import (
    run as run,
)
from private_workspace_allocator import (
    trusted as trusted,
)
from private_workspace_allocator import (
    uuid as uuid,
)
from private_workspace_native_proof import NativeProof as NativeProof


def serve(allocator, socket_path, key):
    def expired(signum, frame):
        raise TimeoutError("allocator request deadline exceeded")

    # Serial main-thread UDS service: also interrupt synchronous filesystem calls,
    # not just socket I/O and each individual child process.
    signal.signal(signal.SIGALRM, expired)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            token = DEADLINE.set(time.monotonic() + REQUEST_SECONDS)
            signal.setitimer(signal.ITIMER_REAL, REQUEST_SECONDS)
            try:
                try:
                    peer = struct.unpack(
                        "3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    )[1]
                    data = self.rfile.readline(MAX_BODY + 1)
                    if len(data) > MAX_BODY or not data.endswith(b"\n"):
                        raise ValueError("bounded JSON required")
                    request = allocator.authenticate(json.loads(data), key, peer)
                    receipt = allocator.ensure(request)
                    result = {"ok": True, "receipt": receipt, "nonce": request["nonce"]}
                    result["mac"] = hmac.new(key, canonical(result), hashlib.sha256).hexdigest()
                except Exception:
                    result = {"ok": False, "error": "private_workspace_refused"}
                try:
                    self.request.settimeout(min(5, remaining()))
                    self.wfile.write(canonical(result) + b"\n")
                except (OSError, TimeoutError):
                    pass  # No new response budget after the absolute deadline.
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                DEADLINE.reset(token)

    # ponytail: one bounded serial service; raise throughput only after filesystem locks
    # remain authoritative.
    trusted(socket_path.parent)
    if socket_path.exists():
        if not stat.S_ISSOCK(socket_path.lstat().st_mode):
            raise ValueError("foreign socket path")
        socket_path.unlink()
    with socketserver.UnixStreamServer(str(socket_path), Handler) as server:
        os.chown(socket_path, 0, allocator.worker_uid)
        os.chmod(socket_path, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    options = parser.parse_args()
    trusted(options.config, directory=False)
    if options.config.stat().st_mode & 0o077:
        raise ValueError("config must be private")
    config = json.loads(options.config.read_text())
    proof = NativeProof(config)
    proof.require_clean()
    generation = config.get("generation", "native105")
    roots = {
        "native105": (ROOT, STATE),
        "cloud114": (
            Path("/var/lib/zebra/erpnext-full-workspaces"),
            Path("/var/lib/zebra/erpnext-full-volumes"),
        ),
        "cloud114-qa": (
            Path("/var/lib/zebra/erpnext-full-qa-workspaces"),
            Path("/var/lib/zebra/erpnext-full-qa-volumes"),
        ),
    }
    root, state = roots[generation]
    allocator = Allocator(proof, root=root, state=state, worker_uid=config["worker_host_uid"])
    key_path = Path(config["hmac_key_path"])
    trusted(key_path, directory=False)
    if key_path.stat().st_mode & 0o077:
        raise ValueError("key must be private")
    key = key_path.read_bytes()
    if len(key) < 32:
        raise ValueError("insufficient HMAC key")
    allocator.restore()
    serve(allocator, Path(config["socket_path"]), key)
