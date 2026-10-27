import sys
import time
from threading import Event, Timer

import pytest
from agent_core.domain.leases import LeaseLostError
from agent_runtime.process_execution import run_process_tree


def test_cancel_interrupts_a_live_process_and_private_stdin_has_no_argv_data() -> None:
    cancelled = Event()

    def check() -> None:
        if cancelled.is_set():
            raise LeaseLostError("owned test revoked")

    timer = Timer(0.15, cancelled.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(LeaseLostError):
            run_process_tree(
                (sys.executable, "-c", "import time; time.sleep(4)"),
                timeout=5,
                max_output_bytes=256,
                input_bytes=b"private-test-only",
                cancellation_check=check,
            )
    finally:
        timer.cancel()
    assert time.monotonic() - start < 1


def test_large_private_stdin_is_pumped_without_blocking_or_argv_leak() -> None:
    from hashlib import sha256

    raw = b"owned-private-test-" * 12000
    result = run_process_tree(
        (
            sys.executable,
            "-c",
            "import sys,hashlib; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()); "
            "print(len(sys.argv))",
        ),
        timeout=2,
        max_output_bytes=256,
        input_bytes=raw,
    )
    assert result.stdout.splitlines() == [sha256(raw).hexdigest(), "1"]


def test_stdin_backpressure_obeys_timeout() -> None:
    from subprocess import TimeoutExpired

    start = time.monotonic()
    with pytest.raises(TimeoutExpired):
        run_process_tree(
            (sys.executable, "-c", "import time; time.sleep(5)"),
            timeout=0.15,
            max_output_bytes=256,
            input_bytes=b"x" * 240000,
        )
    assert time.monotonic() - start < 1


def test_cancel_still_works_after_child_closes_all_output() -> None:
    cancelled = Event()

    def check():
        if cancelled.is_set():
            raise LeaseLostError("owned revocation")

    timer = Timer(0.2, cancelled.set)
    timer.start()
    try:
        with pytest.raises(LeaseLostError):
            run_process_tree(
                (sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(5)"),
                timeout=4,
                max_output_bytes=256,
                cancellation_check=check,
            )
    finally:
        timer.cancel()


@pytest.mark.skipif(sys.platform != "darwin", reason="actual native Seatbelt cancellation")
def test_actual_script_runner_cancels_and_destroys_owned_handle() -> None:
    from agent_runtime import OsSandboxRuntime
    from agent_runtime.native_script import NativeScriptRunner

    from tests.agent_runtime.test_native_script_runner import PYTHON, package, spec

    runtime = OsSandboxRuntime(spec())
    script, raw = package(
        source="def execute(arguments):\n    import time\n    time.sleep(5)\n"
        "    return {'value':'late'}\n"
    )
    cancelled = Event()
    timer = Timer(0.2, cancelled.set)

    def check():
        if cancelled.is_set():
            raise LeaseLostError("owned cancellation")

    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(LeaseLostError):
            NativeScriptRunner(runtime, spec(), python=PYTHON).run(
                script, raw, cancellation_check=check
            )
    finally:
        timer.cancel()
    assert time.monotonic() - start < 1
    assert not runtime._handles


def test_oci_stdin_and_cancellation_destroy_exact_container(tmp_path) -> None:
    from agent_core.ports.runtime import RuntimeExecutionRequest
    from agent_runtime import OciRuntime

    from tests.agent_runtime.test_oci_runtime import FakeEngine, _spec

    class Engine(FakeEngine):
        def __call__(self, command, **kwargs):
            if "exec" in command and "python" in command:
                assert "--interactive" in command
                assert kwargs["input_bytes"] == b"private"
                kwargs["cancellation_check"]()
            return super().__call__(command, **kwargs)

    engine = Engine()
    runtime = OciRuntime(_spec(tmp_path), runner=engine)
    runtime.provision()

    def check():
        raise LeaseLostError("original fence lost")

    with pytest.raises(LeaseLostError):
        runtime.execute(
            RuntimeExecutionRequest(
                command=("python",), stdin_input=b"private", cancellation_check=check
            )
        )
    assert any("rm" in command and "container-1" in command for command in engine.calls)
