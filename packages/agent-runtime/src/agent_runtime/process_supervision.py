"""Bounded private process-group supervision; no application or model dependencies."""

import logging
import os
import signal
import subprocess
import time
from typing import Any


def _running(process: subprocess.Popen[Any]) -> bool:
    if hasattr(os, "waitid"):
        return os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None
    return process.poll() is None  # local test compatibility; Cloud requires waitid


def terminate_group(process: subprocess.Popen[Any], *, grace: float = 2) -> bool:
    """Signal the private, unreaped leader's group before its PID can be reused."""
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            if not hasattr(os, "waitid") or _running(process):
                time.sleep(grace)
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait(timeout=5)
    # A remaining group (including unreaped descendants) is not an exit proof.
    deadline = time.monotonic() + 2
    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def supervise_process(
    process: subprocess.Popen[Any], cancelled: Any, *, interval: float = 0.5, on_exit: Any = None
) -> bool:
    requested = False
    try:
        while _running(process):
            try:
                stopped = cancelled()
            except Exception:
                logging.warning("session_stop_monitor_unavailable")
                stopped = False
            if stopped:
                requested = True
                break
            time.sleep(interval)
    finally:
        exited = terminate_group(process)
        if exited and on_exit is not None:
            try:
                on_exit()
            except Exception:
                # Lost ACK cannot reverse a committed answer or authorize model replay.
                logging.warning("session_executor_exit_ack_unavailable")
    return requested
