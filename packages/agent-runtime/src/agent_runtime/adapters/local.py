from subprocess import TimeoutExpired, run

from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimeExecutionResult, RuntimePort


def _normalize_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


class LocalRuntime(RuntimePort):
    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        try:
            completed = run(
                request.command,
                capture_output=True,
                text=True,
                cwd=request.cwd,
                env=dict(request.env) if request.env is not None else None,
                timeout=request.timeout_seconds,
                check=False,
            )
        except TimeoutExpired as exc:
            return RuntimeExecutionResult(
                command=request.command,
                exit_code=None,
                stdout=_normalize_output(exc.stdout),
                stderr=_normalize_output(exc.stderr),
                timed_out=True,
            )

        return RuntimeExecutionResult(
            command=request.command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )
