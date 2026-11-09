"""Bounded private process-group supervision; no application or model dependencies."""

import logging
import math
import os
import select
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
    pidfd = None
    try:
        try:
            pidfd = os.pidfd_open(process.pid)
        except (AttributeError, OSError):
            pass  # Kernels without pidfds retain the bounded sleep.
        poller = None
        if pidfd is not None:
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
        while _running(process):
            try:
                stopped = cancelled()
            except Exception:
                logging.warning("session_stop_monitor_unavailable")
                stopped = False
            if stopped:
                requested = True
                break
            if poller is None:
                time.sleep(interval)
            else:
                # Readiness does not reap the leader. terminate_group still owns exit proof.
                poller.poll(math.ceil(interval * 1000))
    finally:
        if pidfd is not None:
            os.close(pidfd)
        exited = terminate_group(process)
        if exited and on_exit is not None:
            try:
                on_exit()
            except Exception:
                # Lost ACK cannot reverse a committed answer or authorize model replay.
                logging.warning("session_executor_exit_ack_unavailable")
    return requested
