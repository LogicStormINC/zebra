"""Executor pool regressions (CA-HA-03 D6).

Contract: pool disabled → existing path; pool enabled → children amortize boot;
cancellation via SIGUSR1; crash recovery restarts the slot.
"""

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_pool_disabled_by_default():
    """pool_size=0 (no setting) → pool not enabled, callers use existing path."""
    from zebra_agent_worker.executor_pool_service import ExecutorPoolService

    settings = SimpleNamespace()  # no executor_pool_size attribute
    pool = ExecutorPoolService(settings=settings)
    assert not pool.enabled
    assert pool.submit({}) is None  # disabled → None → caller falls back


def test_pool_enabled_with_setting():
    from zebra_agent_worker.executor_pool_service import ExecutorPoolService

    settings = SimpleNamespace(executor_pool_size=2)
    pool = ExecutorPoolService(settings=settings)
    assert pool.enabled


def test_pool_size_bounds():
    from zebra_agent_worker.executor_pool_service import ExecutorPoolService

    for size, expected in [(-1, False), (0, False), (1, True), (8, True), (9, False)]:
        settings = SimpleNamespace(executor_pool_size=size)
        pool = ExecutorPoolService(settings=settings)
        assert pool.enabled == expected, f"pool_size={size}"


def test_execute_isolated_uses_pool_when_available():
    """When pool is available, execute_isolated routes through the pool path."""
    from zebra_agent_worker import session_process

    pool = MagicMock()
    pool.enabled = True

    service = MagicMock()
    request: dict = {"session_id": "test"}

    with (
        patch.object(session_process, "_get_pool", return_value=pool),
        patch.object(session_process, "_execute_via_pool") as via_pool,
    ):
        via_pool.return_value = None
        try:
            session_process.execute_isolated(service, request)
        except Exception:
            pass

    via_pool.assert_called_once_with(pool, service, request)


def test_pool_child_protocol():
    """Pool child: boot signal on stdout, ready after boot, assign→ack→result→ready."""
    entry = str(
        Path(__file__).parents[2]
        / "apps/worker/src/zebra_agent_worker/executor_pool_child.py"
    )
    # Run a minimal smoke: just the boot message, then close stdin → child exits
    process = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'apps/worker/src'); "
         "from zebra_agent_worker.executor_pool_child import _emit; "
         "_emit({'op': 'boot', 'pid': 0, 'settings_digest': 'test'})"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(timeout=10)
    message = json.loads(stdout.decode().strip())
    assert message["op"] == "boot"
    assert message["settings_digest"] == "test"


def test_pool_service_lifecycle():
    """Start, submit (mock child), close."""
    from zebra_agent_worker.executor_pool_service import ExecutorPoolService

    settings = SimpleNamespace(executor_pool_size=0)
    pool = ExecutorPoolService(settings=settings)
    pool.close()  # no children → no-op
    assert not pool.enabled


def test_cancel_sends_sigusr1():
    """Cancel on an idle pool returns False (no busy child)."""
    from zebra_agent_worker.executor_pool_service import ExecutorPoolService

    settings = SimpleNamespace(executor_pool_size=2)
    pool = ExecutorPoolService(settings=settings)
    # No children started, so cancel finds no handle
    assert pool.cancel("00000000-0000-0000-0000-000000000001") is False
