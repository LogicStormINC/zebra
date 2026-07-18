from __future__ import annotations

import os
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import PIPE, CompletedProcess, Popen, TimeoutExpired


def run_process_tree(
    command: Sequence[str],
    *,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    timeout: float | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CompletedProcess[str]:

    if not capture_output or not text or check:
        raise ValueError("runtime process execution requires captured text output and check=False")
    process = Popen(
        tuple(command),
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        cwd=cwd,
        env=env,
        start_new_session=os.name == "posix",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except TimeoutExpired as exc:
        _terminate_process_tree(process.pid)
        stdout, stderr = process.communicate()
        raise TimeoutExpired(tuple(command), timeout or 0, stdout, stderr) from exc
    return CompletedProcess(tuple(command), process.returncode, stdout, stderr)


def _terminate_process_tree(pid: int) -> None:
    if os.name != "posix":
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    # ponytail: one immediate SIGKILL closes the race without adding a timer thread.
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
