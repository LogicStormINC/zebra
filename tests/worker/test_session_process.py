"""No model: real hung executor process, signal escalation and sibling isolation."""

import os
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.session_process import process_factory, supervise, terminate_group


def child(code):
    return subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )


def test_hung_executor_is_killed_without_stopping_shared_worker_or_sibling():
    parent_pid = os.getpid()
    sibling = child("print('ready'); import time; time.sleep(60)")
    process = child(
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready'); time.sleep(60)"
    )
    try:
        assert sibling.stdout.readline().strip() == process.stdout.readline().strip() == "ready"
        started = time.monotonic()
        with pytest.raises(ExecutionInterrupted):
            supervise(process, lambda: True, interval=0.01)
        assert time.monotonic() - started < 5
        assert process.returncode == -signal.SIGKILL
        assert sibling.poll() is None and os.getpid() == parent_pid
    finally:
        terminate_group(process, grace=0.01)
        terminate_group(sibling, grace=0.01)


@pytest.mark.skipif(not hasattr(os, "pidfd_open"), reason="requires Linux pidfd")
def test_executor_exit_wakes_before_next_cancellation_poll():
    process = child("import time; time.sleep(.15)")
    acknowledged = []
    started = time.monotonic()
    try:
        supervise(process, lambda: False, interval=2, on_exit=lambda: acknowledged.append(True))
        assert time.monotonic() - started < 2
        assert process.returncode == 0 and acknowledged == [True]
    finally:
        terminate_group(process, grace=0.01)


def test_database_uncertainty_does_not_authorize_killing_executor():
    process = child("import time; time.sleep(.1)")
    calls = []

    def unavailable():
        calls.append(True)
        raise TimeoutError()

    supervise(process, unavailable, interval=0.01)
    assert calls and process.returncode == 0


def test_default_and_child_execution_stay_in_process(monkeypatch):
    settings = SimpleNamespace(storage_authority="postgresql", deployment="cloud")
    monkeypatch.delenv("ZEBRA_SESSION_PROCESS_FACTORY", raising=False)
    assert process_factory(settings) is None
    monkeypatch.setenv("ZEBRA_SESSION_PROCESS_FACTORY", "default")
    monkeypatch.setenv("ZEBRA_SESSION_PROCESS_CHILD", "1")
    assert process_factory(settings) is None
    monkeypatch.delenv("ZEBRA_SESSION_PROCESS_CHILD")
    if hasattr(os, "waitid"):
        assert process_factory(settings) == "default"
    else:
        with pytest.raises(ValueError, match="waitid"):
            process_factory(settings)
    with pytest.raises(ValueError):
        process_factory(SimpleNamespace(storage_authority="sqlite", deployment="local"))


def test_unknown_child_outcome_suspends_without_model_retry(tmp_path, monkeypatch):
    from agent_core.domain.sessions import SessionStatus
    from zebra_agent_worker.execution_errors import WorkerExecutorInterrupted

    from tests.worker.execution.worker_execution_support import (
        _build_execution_service,
        _seed_ready_session,
    )

    path = tmp_path / "unknown.db"
    session = _seed_ready_session(path, tmp_path)
    service = _build_execution_service(path)
    monkeypatch.setattr("zebra_agent_worker.execution.process_factory", lambda _: "default")

    def unknown(*args, **kwargs):
        raise WorkerExecutorInterrupted("executor receipt lost")

    def forbidden(*args, **kwargs):
        raise AssertionError("must not call a model")

    monkeypatch.setattr("zebra_agent_worker.execution.execute_isolated", unknown)
    monkeypatch.setattr("zebra_agent_worker.execution.build_model_gateway", forbidden)
    result = service.execute_session(session, worker_id="isolated-parent")
    assert result.session.status is SessionStatus.SUSPENDED
    assert result.attempt_result.metadata["retryable"] is False
    assert result.attempt_result.metadata["stop_reason"] == "executor_process_interrupted"
    assert service._projection_store.list_ready_sessions(limit=10) == []


def test_execution_receipt_roundtrip_preserves_body_and_identity(tmp_path, monkeypatch):
    from pydantic import TypeAdapter
    from zebra_agent_worker.execution_finalization import ExecutedSession

    from tests.worker.execution.worker_execution_support import (
        _assistant_only_gateway,
        _build_execution_service,
        _seed_ready_session,
    )

    path = tmp_path / "receipt.db"
    session = _seed_ready_session(path, tmp_path)
    service = _build_execution_service(path)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    result = service.execute_session(session, worker_id="receipt-parent")
    adapter = TypeAdapter(ExecutedSession)
    restored = adapter.validate_json(adapter.dump_json(result))
    assert restored == result
    assert restored.session.session_id == session
    assert restored.attempt_result.metadata["assistant_message"] == "Worker completed the session."


@pytest.mark.parametrize("repeated", [False, True])
def test_initial_recovery_retries_one_lock_timeout_under_same_lease(repeated):
    from unittest.mock import Mock, call

    from psycopg.errors import LockNotAvailable
    from zebra_agent_worker.bounded_session_recovery import SessionRecoveryPending
    from zebra_agent_worker.session_process_child import recover_initial_session

    pending = SessionRecoveryPending("busy")
    pending.__cause__ = LockNotAvailable()
    result = object()
    service = Mock()
    service.recover_session.side_effect = [pending, pending if repeated else result]
    lease = Mock()
    if repeated:
        with pytest.raises(SessionRecoveryPending):
            recover_initial_session(service, lease)
    else:
        assert recover_initial_session(service, lease) is result
    assert (
        service.recover_session.call_args_list == [call(lease.session_id, worker_lease=lease)] * 2
    )
