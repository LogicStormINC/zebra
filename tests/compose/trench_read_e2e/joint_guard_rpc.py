"""Persistent QA transport only; every request executes the unchanged full guard."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import BinaryIO, TextIO


def full_guard(environment: Mapping[str, str], remaining_ms: float) -> int:
    from agent_storage.postgres.task_io import task_io_deadline
    from joint_acceptance import run_joint

    with task_io_deadline(time.monotonic() + remaining_ms / 1000):
        # guard=True returns before evidence writes. No cached Config/proof or reduced checks.
        return run_joint(environment, Path("."), preflight_only=True, guard=True)


def serve(
    source: BinaryIO,
    output: TextIO,
    check: Callable[[float], int],
) -> int:
    for _ in range(4096):
        raw = source.readline(4097)
        if not raw:
            return 0
        try:
            if len(raw) > 4096 or not raw.endswith(b"\n"):
                return 2
            request = json.loads(raw)
            if not isinstance(request, dict) or set(request) != {
                "request_id",
                "op",
                "remaining_ms",
            }:
                return 2
            request_id = request["request_id"]
            remaining = request["remaining_ms"]
            if (
                not isinstance(request_id, str)
                or not re.fullmatch(r"[a-f0-9-]{36}", request_id)
                or request["op"] != "guard"
                or type(remaining) not in (int, float)
                or not math.isfinite(remaining)
                or not 0 < remaining <= 30000
            ):
                return 2
            try:
                # Never let imported code print credentials or protocol-shaped output.
                with redirect_stdout(None), redirect_stderr(None):
                    passed = check(float(remaining)) == 0
            except Exception:
                passed = False
            output.write(
                json.dumps({"request_id": request_id, "status": "passed" if passed else "denied"})
                + "\n"
            )
            output.flush()
        except (UnicodeError, ValueError, TypeError, OSError):
            return 2
    return 2


def main() -> int:
    # Import once before the browser's startup guard returns, never once per mutation.
    from agent_storage.postgres.database import PostgresDatabase  # noqa: F401
    from agent_storage.postgres.migrations import MIGRATIONS  # noqa: F401

    return serve(sys.stdin.buffer, sys.stdout, lambda remaining: full_guard(os.environ, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
