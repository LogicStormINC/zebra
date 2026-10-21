from __future__ import annotations

import os
import signal
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from selectors import EVENT_READ, DefaultSelector
from subprocess import PIPE, CompletedProcess, Popen, TimeoutExpired
from threading import Thread
from typing import BinaryIO


class CapturedProcessResult(CompletedProcess[str]):
    stdout_truncated: bool
    stderr_truncated: bool

    def __init__(
        self,
        args: Sequence[str],
        returncode: int,
        stdout: str,
        stderr: str,
        *,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
    ) -> None:
        super().__init__(tuple(args), returncode, stdout, stderr)
        self.stdout_truncated = stdout_truncated
        self.stderr_truncated = stderr_truncated


class _BoundedCapture:
    def __init__(self, maximum_bytes: int) -> None:
        self._maximum_bytes = maximum_bytes
        self._chunks: list[bytes] = []
        self._length = 0
        self.truncated = False

    def append(self, chunk: bytes) -> None:
        remaining = self._maximum_bytes - self._length
        if remaining > 0:
            retained = chunk[:remaining]
            self._chunks.append(retained)
            self._length += len(retained)
        if len(chunk) > max(remaining, 0):
            self.truncated = True

    def drain(self, stream: BinaryIO) -> None:
        while chunk := stream.read(65_536):
            self.append(chunk)

    def text(self) -> str:
        return b"".join(self._chunks).decode(
            "utf-8", errors="ignore" if self.truncated else "replace"
        )


def run_process_tree(
    command: Sequence[str],
    *,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    timeout: float | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int | None = None,
) -> CompletedProcess[str]:
    if not capture_output or not text or check:
        raise ValueError("runtime process execution requires captured text output and check=False")
    if max_output_bytes is not None and max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")
    if max_output_bytes is not None:
        return _run_bounded(
            command,
            timeout=timeout,
            cwd=cwd,
            env=env,
            max_output_bytes=max_output_bytes,
        )
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
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise TimeoutExpired(tuple(command), timeout or 0, stdout, stderr) from exc
    return CompletedProcess(tuple(command), process.returncode, stdout, stderr)


def _run_bounded(
    command: Sequence[str],
    *,
    timeout: float | None,
    cwd: str | Path | None,
    env: Mapping[str, str] | None,
    max_output_bytes: int,
) -> CapturedProcessResult:
    process = Popen(
        tuple(command),
        stdout=PIPE,
        stderr=PIPE,
        cwd=cwd,
        env=env,
        start_new_session=os.name == "posix",
    )
    if os.name == "posix":
        return _capture_posix(process, command, timeout, max_output_bytes)
    assert process.stdout is not None and process.stderr is not None
    stdout = _BoundedCapture(max_output_bytes)
    stderr = _BoundedCapture(max_output_bytes)
    readers = (
        Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
        Thread(target=stderr.drain, args=(process.stderr,), daemon=True),
    )
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    except TimeoutExpired as exc:
        _terminate_process_tree(process)
        process.wait()
        for reader in readers:
            reader.join()
        failure = TimeoutExpired(tuple(command), timeout or 0, stdout.text(), stderr.text())
        failure.stdout_truncated = stdout.truncated  # type: ignore[attr-defined]
        failure.stderr_truncated = stderr.truncated  # type: ignore[attr-defined]
        raise failure from exc
    for reader in readers:
        reader.join()
    return CapturedProcessResult(
        command,
        process.returncode,
        stdout.text(),
        stderr.text(),
        stdout_truncated=stdout.truncated,
        stderr_truncated=stderr.truncated,
    )


def _capture_posix(
    process: Popen[bytes],
    command: Sequence[str],
    timeout: float | None,
    limit: int,
) -> CapturedProcessResult:
    """Use one deadline for leader exit AND inherited-pipe drain, without threads."""
    assert process.stdout is not None and process.stderr is not None
    stdout, stderr = _BoundedCapture(limit), _BoundedCapture(limit)
    deadline = None if timeout is None else time.monotonic() + timeout

    def remaining() -> float | None:
        if deadline is None:
            return None
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutExpired(command, timeout or 0)
        return budget

    try:
        with DefaultSelector() as selector:
            selector.register(process.stdout, EVENT_READ, stdout)
            selector.register(process.stderr, EVENT_READ, stderr)
            while selector.get_map():
                for key, _ in selector.select(remaining()):
                    chunk = os.read(key.fd, 65_536)
                    if chunk:
                        key.data.append(chunk)
                    else:
                        selector.unregister(key.fd)
            process.wait(timeout=remaining())
    except TimeoutExpired as exc:
        _terminate_process_tree(process)
        process.wait()
        failure = TimeoutExpired(tuple(command), timeout or 0, stdout.text(), stderr.text())
        failure.stdout_truncated = stdout.truncated  # type: ignore[attr-defined]
        failure.stderr_truncated = stderr.truncated  # type: ignore[attr-defined]
        raise failure from exc
    except BaseException:
        _terminate_process_tree(process)
        process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
    return CapturedProcessResult(
        command,
        process.returncode,
        stdout.text(),
        stderr.text(),
        stdout_truncated=stdout.truncated,
        stderr_truncated=stderr.truncated,
    )


def _terminate_process_tree(process: Popen[str] | Popen[bytes]) -> None:
    if os.name != "posix":
        process.terminate()
        process.kill()
        return
    # ponytail: timeouts have no grace period; one group KILL avoids the TERM/exit/KILL race.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
