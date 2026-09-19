import sys
from subprocess import TimeoutExpired

import pytest
from agent_runtime.process_execution import run_process_tree


def test_bounded_capture_drains_both_streams_without_retaining_overflow() -> None:
    result = run_process_tree(
        (
            sys.executable,
            "-c",
            "import os; os.write(1, b'abcdef'); os.write(2, b'ghijkl')",
        ),
        max_output_bytes=4,
    )

    assert result.stdout == "abcd"
    assert result.stderr == "ghij"
    assert result.stdout_truncated is True  # type: ignore[attr-defined]
    assert result.stderr_truncated is True  # type: ignore[attr-defined]


def test_bounded_capture_preserves_limit_and_flags_on_timeout() -> None:
    with pytest.raises(TimeoutExpired) as raised:
        run_process_tree(
            (
                sys.executable,
                "-c",
                "import os,time; os.write(1, b'abcdef'); os.write(2, b'ghijkl'); time.sleep(30)",
            ),
            timeout=0.1,
            max_output_bytes=4,
        )

    assert raised.value.stdout == "abcd"
    assert raised.value.stderr == "ghij"
    assert raised.value.stdout_truncated is True  # type: ignore[attr-defined]
    assert raised.value.stderr_truncated is True  # type: ignore[attr-defined]
