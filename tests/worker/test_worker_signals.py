"""CLI termination requests orderly drain; it is never a quiescence proof."""
from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
from pathlib import Path
from threading import Thread

import pytest


def test_real_idle_cli_sigterm_exits_through_normal_summary(tmp_path: Path) -> None:
    source = f"""
import sys
sys.path.insert(0, {str(Path(__file__).parent)!r})
from test_loop import _settings
import zebra_agent_worker.main as cli
from zebra_agent_worker.worker_loop_service import WorkerLoopService
cli.load_settings = lambda: _settings(__import__('pathlib').Path({str(tmp_path / 'worker.db')!r}))
original = WorkerLoopService.poll_once
def poll(self, **kwargs):
    result = original(self, **kwargs)
    print('OWNED_WORKER_READY', flush=True)
    return result
WorkerLoopService.poll_once = poll
raise SystemExit(cli.main([]))
"""
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", source], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        assert child.stdout is not None
        assert select.select([child.stdout], [], [], 15)[0], "owned CLI startup timed out"
        assert child.stdout.readline().strip() == "OWNED_WORKER_READY"
        child.send_signal(signal.SIGTERM)
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, (child.returncode, stderr)
        assert '"stop_reason": "signal"' in stdout
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_scoped_signal_handlers_restore_even_after_failure() -> None:
    from zebra_agent_worker.worker_signals import worker_stop_signals
    previous = {s: signal.getsignal(s) for s in [signal.SIGINT, signal.SIGTERM]}
    with pytest.raises(RuntimeError), worker_stop_signals() as stopped:
        assert not stopped()
        signal.raise_signal(signal.SIGTERM)
        assert stopped()
        raise RuntimeError("owned test failure")
    assert {s: signal.getsignal(s) for s in previous} == previous


def test_embedded_thread_does_not_own_process_signals() -> None:
    from zebra_agent_worker.worker_signals import worker_stop_signals
    previous = signal.getsignal(signal.SIGTERM)
    result = []
    def embedded() -> None:
        with worker_stop_signals() as stopped:
            result.append(stopped())
    thread = Thread(target=embedded)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive() and result == [False]
    assert signal.getsignal(signal.SIGTERM) == previous
