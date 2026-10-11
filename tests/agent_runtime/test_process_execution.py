import os
import signal
import sys
from subprocess import Popen, TimeoutExpired
from unittest.mock import Mock

import pytest
from agent_runtime.process_execution import _terminate_process_tree, run_process_tree


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

    stdout: object = raised.value.stdout  # TimeoutExpired's stubs omit captured text output.
    stderr: object = raised.value.stderr
    assert isinstance(stdout, str) and stdout == "abcd"
    assert isinstance(stderr, str) and stderr == "ghij"
    assert raised.value.stdout_truncated is True  # type: ignore[attr-defined]
    assert raised.value.stderr_truncated is True  # type: ignore[attr-defined]


@pytest.mark.skipif(os.name != "posix", reason="process groups require POSIX")
def test_tree_cleanup_avoids_term_exit_kill_permission_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock(spec=Popen, pid=12345)
    process.poll.return_value = 0  # An exited leader must not spare its live descendants.
    signals: list[tuple[int, int]] = []

    def kill_group(pid: int, sig: int) -> None:
        signals.append((pid, sig))
        if len(signals) > 1:
            raise PermissionError("group exited between TERM and KILL")

    monkeypatch.setattr(os, "killpg", kill_group)
    _terminate_process_tree(process)
    assert signals == [(process.pid, signal.SIGKILL)]
    process.poll.assert_not_called()


@pytest.mark.skipif(os.name != "posix", reason="process groups require POSIX")
def test_tree_cleanup_accepts_only_missing_group(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock(spec=Popen, pid=12345)
    kill_group = Mock(side_effect=ProcessLookupError("group is gone"))
    monkeypatch.setattr(os, "killpg", kill_group)
    _terminate_process_tree(process)
    kill_group.assert_called_once_with(process.pid, signal.SIGKILL)


@pytest.mark.skipif(os.name != "posix", reason="process groups require POSIX")
def test_tree_cleanup_does_not_hide_genuine_permission_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock(spec=Popen, pid=12345)
    kill_group = Mock(side_effect=PermissionError("not authorized to terminate group"))
    monkeypatch.setattr(os, "killpg", kill_group)
    with pytest.raises(PermissionError, match="not authorized"):
        _terminate_process_tree(process)
    kill_group.assert_called_once_with(process.pid, signal.SIGKILL)
