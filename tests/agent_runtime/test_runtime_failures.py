from agent_runtime.runtime_failures import normalize_runtime_failure


def test_runtime_failures_normalize_timeout_disk_and_command_errors() -> None:
    assert normalize_runtime_failure(timed_out=True, exit_code=None, stderr="") == "timeout"
    assert (
        normalize_runtime_failure(
            timed_out=False,
            exit_code=1,
            stderr="write: No space left on device",
        )
        == "workspace_quota_exceeded"
    )
    assert normalize_runtime_failure(timed_out=False, exit_code=7, stderr="boom") == (
        "command_failed"
    )
    assert normalize_runtime_failure(timed_out=False, exit_code=0, stderr="") is None
