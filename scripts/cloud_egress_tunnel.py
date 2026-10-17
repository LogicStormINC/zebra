"""Operator-owned, foreground prebuilt SSH egress. No Agent credentials or global proxy edits."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import socket
import sys


def command(argv: list[str]) -> list[str]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ssh_host", help="Existing verified SSH host/config alias")
    parser.add_argument("--port", type=int, default=18446)
    parser.add_argument(
        "--interface", help="Optional host-only physical interface (native macOS nc)"
    )
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", args.ssh_host):
        parser.error("invalid SSH host")
    if not 0 < args.port < 65536:
        parser.error("invalid listener port")
    ssh = shutil.which("ssh")
    if ssh is None:
        parser.error("native SSH client unavailable")
    result = [
        ssh,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=3",
    ]
    if args.interface:
        if sys.platform != "darwin":
            parser.error("interface binding is an operator macOS option")
        socket.if_nametoindex(args.interface)
        result += ["-o", "ProxyCommand=/usr/bin/nc -b " + shlex.quote(args.interface) + " %h %p"]
    # ponytail: SSH owns the persistent encrypted transport; an operator supervisor
    # owns restart. Never rebuild SSH per request or let the Agent manage its keys.
    return [*result, "-N", "-D", f"127.0.0.1:{args.port}", args.ssh_host]


if __name__ == "__main__":
    args = command(sys.argv[1:])
    os.execv(args[0], args)
