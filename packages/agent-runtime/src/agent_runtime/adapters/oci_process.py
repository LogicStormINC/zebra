"""OCI command transport with bounded administration, input and cancellation."""

from collections.abc import Callable, Sequence
from subprocess import CompletedProcess, TimeoutExpired
from typing import Any

from agent_core.ports.runtime import RuntimeCapabilityError


def invoke_oci_process(
    runner: Callable[..., CompletedProcess[str]],
    command: Sequence[str],
    *,
    cloud: bool,
    timeout: float | None = None,
    max_output_bytes: int | None = None,
    input_bytes: bytes | None = None,
    cancellation_check: Callable[[], None] | None = None,
) -> CompletedProcess[str]:
    try:
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "check": False,
            "timeout": 30 if cloud and timeout is None else timeout,
        }
        if max_output_bytes is not None:
            kwargs["max_output_bytes"] = max_output_bytes
        if input_bytes is not None:
            kwargs["input_bytes"] = input_bytes
        if cancellation_check is not None:
            kwargs["cancellation_check"] = cancellation_check
        return runner(tuple(command), **kwargs)
    except TimeoutExpired:
        if cloud and timeout is None:
            raise RuntimeCapabilityError("cloud runtime administration timed out") from None
        raise


def engine_failure(operation: str, completed: CompletedProcess[str]) -> str:
    detail = (completed.stderr or completed.stdout).strip()[:2048]
    return f"OCI {operation} failed" + (f": {detail}" if detail else "")
