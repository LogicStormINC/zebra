def normalize_runtime_failure(
    *,
    timed_out: bool,
    exit_code: int | None,
    stderr: str,
) -> str | None:
    if timed_out:
        return "timeout"
    if exit_code == 0:
        return None
    if "no space left on device" in stderr.lower():
        return "workspace_quota_exceeded"
    return "command_failed"
