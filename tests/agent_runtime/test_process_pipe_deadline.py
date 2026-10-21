"""An exited parent must not disable the bounded capture timeout."""

import os
import sys
import time
from subprocess import TimeoutExpired

import pytest
from agent_runtime.process_execution import run_process_tree


@pytest.mark.skipif(os.name != "posix", reason="POSIX inherited pipes")
def test_exited_leader_cannot_keep_capture_waiting_for_its_child() -> None:
    started = time.monotonic()
    with pytest.raises(TimeoutExpired):
        run_process_tree(
            (
                sys.executable,
                "-c",
                "import subprocess,sys; subprocess.Popen("
                "[sys.executable,'-c','import time; time.sleep(1.5)'])",
            ),
            timeout=0.15,
            max_output_bytes=256,
        )
    assert time.monotonic() - started < 1.0
