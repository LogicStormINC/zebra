import pytest
from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeExecutionRequest,
    RuntimeSnapshot,
)
from agent_runtime.adapters.local import LocalRuntime


def test_local_runtime_executes_successfully() -> None:
    runtime = LocalRuntime()

    result = runtime.execute(
        RuntimeExecutionRequest(
            command=(
                "python3",
                "-c",
                "print('runtime-ok')",
            )
        )
    )

    assert result.succeeded is True
    assert result.exit_code == 0
    assert result.stderr == ""
    assert "runtime-ok" in result.stdout


def test_local_runtime_captures_non_zero_exit() -> None:
    runtime = LocalRuntime()

    result = runtime.execute(
        RuntimeExecutionRequest(
            command=(
                "python3",
                "-c",
                "import sys; print('boom'); sys.exit(7)",
            )
        )
    )

    assert result.succeeded is False
    assert result.timed_out is False
    assert result.exit_code == 7
    assert "boom" in result.stdout


def test_local_runtime_reports_timeout() -> None:
    runtime = LocalRuntime()

    result = runtime.execute(
        RuntimeExecutionRequest(
            command=(
                "python3",
                "-c",
                "import time; print('start'); time.sleep(0.2); print('end')",
            ),
            timeout_seconds=0.05,
        )
    )

    assert result.succeeded is False
    assert result.timed_out is True
    assert result.exit_code is None


def test_local_runtime_provision_suspend_and_resume_handle() -> None:
    runtime = LocalRuntime()

    handle = runtime.provision(workspace_root="/tmp/runtime-handle")
    suspended = runtime.suspend(handle)
    resumed = runtime.resume(suspended)

    assert handle.runtime_name == "local"
    assert handle.workspace_root == "/tmp/runtime-handle"
    assert handle.suspended is False
    assert suspended.suspended is True
    assert resumed.suspended is False
    assert resumed.handle_id == handle.handle_id


def test_local_runtime_snapshot_operations_fail_closed() -> None:
    runtime = LocalRuntime()
    handle = runtime.provision(workspace_root="/tmp/runtime-handle")
    snapshot = RuntimeSnapshot.create(
        runtime_name="local",
        source_handle_id=handle.handle_id,
    )

    with pytest.raises(RuntimeCapabilityError, match="does not support snapshot"):
        runtime.snapshot(handle)
    with pytest.raises(RuntimeCapabilityError, match="does not support restore"):
        runtime.restore(snapshot)
    with pytest.raises(RuntimeCapabilityError, match="does not support fork"):
        runtime.fork(snapshot)
