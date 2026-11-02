"""Private Linux subreaper: never confound one executor's descendants with a Worker."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def parent_fence(parent_pid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise RuntimeError("executor parent fence unavailable")


def _children() -> set[int]:
    # Only OUR direct children. Linux reparents escaped/double-fork descendants
    # here; unreaped child PIDs cannot be reused while being signalled.
    result: set[int] = set()
    for task in Path("/proc/self/task").iterdir():
        try:
            result.update(map(int, (task / "children").read_text().split()))
        except FileNotFoundError:
            pass
    return result


def _drain(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 1.5
    while True:
        for pid in _children():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return  # ECHILD, not just a vanished group, proves full reaping
            if pid == 0:
                break
            if pid == process.pid:
                process.returncode = os.waitstatus_to_exitcode(status)
        if time.monotonic() >= deadline:
            raise RuntimeError("executor descendants still unconfirmed")
        time.sleep(0.01)


def run(source: Path, result: Path) -> None:
    if not hasattr(os, "waitid"):
        raise RuntimeError("private supervisor requires Linux waitid")
    request = json.loads(source.read_bytes())
    parent_fence(request["parent_pid"])
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:  # CHILD_SUBREAPER
        raise RuntimeError("executor subreaper unavailable")
    stopping = False

    def stop(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    process = subprocess.Popen(
        [*request["executor_command"], str(os.getpid())],
        start_new_session=True,
    )
    try:
        while not stopping:
            if os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                break
            time.sleep(0.02)
    finally:
        _drain(process)
    # Private supervisor alone writes this, after the kernel reports no children.
    receipt = request["exit_receipt"]
    result.with_suffix(".exit.json").write_text(json.dumps(receipt))
    if process.returncode:
        raise SystemExit(1)


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]))
