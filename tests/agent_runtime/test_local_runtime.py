from agent_core.ports.runtime import RuntimeExecutionRequest
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
