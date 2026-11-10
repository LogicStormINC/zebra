"""Executor pool: manage N long-lived children for amortized task execution (D6)."""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from time import monotonic
from typing import Any, cast

logger = logging.getLogger(__name__)

_ACK_DEADLINE = 5.0
_RESULT_POLL = 0.05


class PoolChildHandle:
    """One managed child process with its stdin/stdout pipes."""

    def __init__(self, process: "subprocess.Popen[bytes]", worker_pid: int) -> None:
        self.process = process
        self.busy = False
        self.task_id: str | None = None
        self.assigned_at: float = 0.0


class ExecutorPoolService:
    """Config-gated pool of long-lived executor children (CA-HA-03 D6).

    pool_size=0 (default) → callers use the existing per-task spawn path.
    pool_size=N → N children amortize the ~2s boot cost across tasks.
    """

    def __init__(
        self,
        *,
        settings: Any,
        env: dict[str, str] | None = None,
        ack_deadline: float = _ACK_DEADLINE,
    ) -> None:
        pool_size = getattr(settings, "executor_pool_size", 0)
        if type(pool_size) is not int or not 0 <= pool_size <= 8:
            pool_size = 0
        self._pool_size = pool_size
        self._settings = settings
        self._env = env or dict(os.environ)
        self._ack_deadline = ack_deadline
        self._children: list[PoolChildHandle] = []
        self._lock = threading.Lock()
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self._pool_size > 0 and not self._closed

    def start(self) -> None:
        """Spawn pool children; each does one-time imports+TLS then signals boot."""
        if self._pool_size == 0 or self._children:
            return
        from zebra_agent_worker.session_process import settings_digest

        settings_digest(self._settings)
        entry = str(Path(__file__).with_name("executor_pool_child.py"))
        for index in range(self._pool_size):
            env = {
                **self._env,
                "ZEBRA_SESSION_PROCESS_CHILD": "1",
                "PYTHONPATH": os.pathsep.join(sys.path),
            }
            process = subprocess.Popen(
                [sys.executable, entry, str(os.getpid())],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=env,
            )
            handle = PoolChildHandle(process, os.getpid())
            self._children.append(handle)
            logger.info("executor_pool_child_started index=%d pid=%d", index, process.pid)

    def submit(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Assign a task to an idle child; returns result dict or None if pool disabled/full.

        Blocks until the child returns a result or the task is cancelled.
        """
        if not self.enabled:
            return None
        with self._lock:
            idle = next((c for c in self._children if not c.busy), None)
            if idle is None:
                return None
            idle.busy = True
            idle.task_id = str(request.get("session_id", ""))
            idle.assigned_at = monotonic()

        task_id = idle.task_id
        try:
            message = json.dumps({
                "op": "assign",
                "task_id": task_id,
                "request": request,
            })
            assert idle.process.stdin is not None
            stdin = idle.process.stdin
            stdin.write(message.encode() + b"\n")
            stdin.flush()

            result = self._read_result(idle, task_id)
            return result
        except (OSError, BrokenPipeError) as error:
            logger.warning("executor_pool_child_error pid=%d error=%s", idle.process.pid, error)
            self._restart(idle)
            return {"outcome": "WorkerExecutorInterrupted", "task_id": task_id}
        finally:
            with self._lock:
                idle.busy = False
                idle.task_id = None

    def _read_result(self, handle: PoolChildHandle, task_id: str) -> dict[str, Any]:
        """Read ack + result from the child's stdout (line-delimited JSON)."""
        deadline = monotonic() + 300  # 5-minute task ceiling
        acked = False
        while monotonic() < deadline:
            assert handle.process.stdout is not None
            stdout = handle.process.stdout
            line = stdout.readline()
            if not line:
                raise BrokenPipeError("pool child closed stdout")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            op = message.get("op")
            if op == "ack" and message.get("task_id") == task_id:
                acked = True
            elif op == "result" and message.get("task_id") == task_id:
                if not acked:
                    logger.warning("pool_child_result_without_ack task=%s", task_id)
                return cast("dict[str, Any]", message)
        return {"outcome": "timeout", "task_id": task_id}

    def cancel(self, session_id: str) -> bool:
        """Send SIGUSR1 to the child executing this session's task."""
        with self._lock:
            handle = next(
                (c for c in self._children if c.task_id == session_id and c.busy), None
            )
        if handle is None:
            return False
        try:
            handle.process.send_signal(signal.SIGUSR1)
            return True
        except ProcessLookupError:
            return False

    def _restart(self, handle: PoolChildHandle) -> None:
        """Kill and respawn a crashed child slot."""
        try:
            handle.process.kill()
            handle.process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        entry = str(Path(__file__).with_name("executor_pool_child.py"))
        env = {
            **self._env,
            "ZEBRA_SESSION_PROCESS_CHILD": "1",
            "PYTHONPATH": os.pathsep.join(sys.path),
        }
        handle.process = subprocess.Popen(
            [sys.executable, entry, str(os.getpid())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        logger.info("executor_pool_child_restarted pid=%d", handle.process.pid)

    def close(self) -> None:
        """SIGTERM all children and wait for exit."""
        with self._lock:
            self._closed = True
        for handle in self._children:
            try:
                handle.process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
        for handle in self._children:
            try:
                handle.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                handle.process.kill()
        self._children.clear()
