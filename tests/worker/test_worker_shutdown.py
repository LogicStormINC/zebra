"""Process-owned shutdown checks; synthetic work only, no external resources."""
import subprocess
import sys
import textwrap

from zebra_agent_worker.worker_shutdown import begin_worker_drain, worker_shutdown_deadline


def test_deadline_begins_once_and_is_cancelled_only_after_scope_exit(monkeypatch):
    import zebra_agent_worker.worker_shutdown as module

    timers = []

    class Timer:
        def __init__(self, seconds, callback):
            self.seconds, self.callback = seconds, callback
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

        def join(self):
            pass

    monkeypatch.setattr(module, "Timer", Timer)
    with worker_shutdown_deadline(timeout_seconds=0.2):
        begin_worker_drain()
        begin_worker_drain()
        assert len(timers) == 1 and timers[0].seconds == 0.2
        assert not timers[0].cancelled
    assert timers[0].cancelled
    begin_worker_drain()  # Library callers outside the process scope remain compatible.
    assert len(timers) == 1


def test_cloud_deadline_exits_with_live_thread_without_closing_dependencies():
    result = subprocess.run([sys.executable, "-c", textwrap.dedent('''
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from contextlib import contextmanager
        from zebra_agent_worker.worker_shutdown import begin_worker_drain, worker_shutdown_deadline
        @contextmanager
        def dependencies():
            try:
                yield
            finally:
                print("DEPENDENCIES_CLOSED", flush=True)
        with worker_shutdown_deadline(timeout_seconds=0.15), dependencies():
            pool = ThreadPoolExecutor(1)
            entered, release = Event(), Event()
            def work():
                entered.set()
                release.wait()
            pool.submit(work)
            assert entered.wait(1)
            begin_worker_drain()
            pool.shutdown(wait=True)
        print("FALSE_SUCCESS", flush=True)
    ''')], capture_output=True, text=True, timeout=5)
    assert result.returncode == 75
    assert "worker_shutdown_deadline_exceeded" in result.stderr
    assert "resources_released=false" in result.stderr
    assert "DEPENDENCIES_CLOSED" not in result.stdout
    assert "FALSE_SUCCESS" not in result.stdout


def test_deadline_remains_active_during_dependency_cleanup():
    result = subprocess.run([sys.executable, "-c", textwrap.dedent('''
        from threading import Event
        from contextlib import contextmanager
        from zebra_agent_worker.worker_shutdown import begin_worker_drain, worker_shutdown_deadline
        @contextmanager
        def dependencies():
            try:
                yield
            finally:
                Event().wait()
        with worker_shutdown_deadline(timeout_seconds=0.1), dependencies():
            begin_worker_drain()
    ''')], capture_output=True, text=True, timeout=5)
    assert result.returncode == 75


def test_disabled_scope_does_not_arm_timer(monkeypatch):
    import zebra_agent_worker.worker_shutdown as module

    monkeypatch.setattr(module, "Timer", lambda *_: (_ for _ in ()).throw(AssertionError()))
    with worker_shutdown_deadline(enabled=False):
        begin_worker_drain()


def test_memory_work_cannot_restart_after_drain_and_batch_stops():
    from threading import Event, Thread
    from types import SimpleNamespace

    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    entered, release, draining = Event(), Event(), Event()
    calls = []

    def deliver(_):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(status="completed")

    service = WorkerLoopService(None, None, memory_delivery=deliver,
                               projection_work=SimpleNamespace(close=draining.set))
    service._start_memory_delivery(worker_id="synthetic", batch_size=3)
    assert entered.wait(2)
    closing = Thread(target=service.drain)
    closing.start()
    try:
        assert draining.wait(2)
        service._start_cloud_memory_recovery(worker_id="synthetic", batch_size=1,
                                             lease_ttl_seconds=30)
    finally:
        release.set()
        closing.join(2)
    assert not closing.is_alive()
    service._start_memory_delivery(worker_id="synthetic", batch_size=1)
    service.drain()
    assert calls == [1]


def test_drain_failure_does_not_replace_original_failure(monkeypatch):
    import pytest
    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    service = WorkerLoopService(None, None)

    def fail(**_):
        raise ValueError("original execution failure")

    def drain():
        raise RuntimeError("cleanup failure")

    monkeypatch.setattr(service, "poll_once", fail)
    monkeypatch.setattr(service, "drain", drain)
    with pytest.raises(ValueError, match="original execution failure") as caught:
        service.run(worker_id="synthetic", max_cycles=1)
    assert "worker drain failed: RuntimeError" in caught.value.__notes__


def test_cleanup_error_still_joins_owned_threads_before_raising():
    import pytest
    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    log = []

    class Closing:
        def close(self):
            log.append("close")
            raise RuntimeError("close failed")

    class Joined:
        def join(self):
            log.append("joined")

    service = WorkerLoopService(None, None, projection_work=Closing())
    service._memory_delivery_thread = Joined()
    with pytest.raises(RuntimeError, match="close failed"):
        service.drain()
    assert log == ["close", "joined"]


def test_signal_arms_deadline_even_when_execution_cannot_return():
    result = subprocess.run([sys.executable, "-c", textwrap.dedent('''
        import os, signal
        from threading import Event
        from zebra_agent_worker.worker_shutdown import worker_shutdown_deadline
        from zebra_agent_worker.worker_signals import worker_stop_signals
        with worker_shutdown_deadline(timeout_seconds=0.1), worker_stop_signals() as stopped:
            os.kill(os.getpid(), signal.SIGTERM)
            assert stopped()
            Event().wait()
    ''')], capture_output=True, text=True, timeout=5)
    assert result.returncode == 75


def test_real_main_keeps_dependencies_open_until_process_failure():
    result = subprocess.run([sys.executable, "-c", textwrap.dedent('''
        import importlib
        from threading import Event
        from types import SimpleNamespace
        from zebra_agent_worker.worker_shutdown import begin_worker_drain, worker_shutdown_deadline
        main = importlib.import_module("zebra_agent_worker.main")
        main.load_settings = lambda: SimpleNamespace(deployment="cloud", database_url="unused",
            storage_authority="sqlite", web_egress_socks_endpoint=None)
        main.worker_shutdown_deadline = lambda **kw: worker_shutdown_deadline(
            **kw, timeout_seconds=0.1)
        class Client:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): print("CLIENT_CLOSED", flush=True)
        class Worker:
            def run(self, **kwargs):
                begin_worker_drain()
                Event().wait()
        main.httpx.Client = Client
        main.build_worker_loop_service = lambda **kw: Worker()
        main.main(["--max-cycles", "1"])
    ''')], capture_output=True, text=True, timeout=5)
    assert result.returncode == 75, result.stderr
    assert "CLIENT_CLOSED" not in result.stdout


def test_closed_worker_rejects_execution_and_does_not_restart_maintenance():
    from types import SimpleNamespace

    import pytest
    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    log = []
    projection = SimpleNamespace(close=lambda: log.append("close"),
                                 start=lambda: log.append("start"))
    worker = WorkerLoopService(None, None, projection_work=projection)
    worker.drain()
    worker.maintenance_once(worker_id="synthetic", batch_size=1, lease_ttl_seconds=30)
    assert log == ["close"]
    with pytest.raises(RuntimeError, match="Worker is stopping"):
        worker.poll_once(worker_id="synthetic")
