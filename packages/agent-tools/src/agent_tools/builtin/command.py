from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimePort
from agent_core.ports.workspace import WorkspacePort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError
from agent_tools.output_projection import ToolOutputProjector

command_run_contract = ToolContract(
    name="command.run",
    required_arguments=("command",),
    description="Run a typed executable plus argv inside the current workspace.",
    argument_properties={
        "command": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Executable followed by argv, without shell parsing.",
        },
        "cwd": {"type": "string", "description": "Optional workspace-relative directory."},
        "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
    },
)


class CommandRunTool:
    def __init__(
        self,
        runtime: RuntimePort,
        workspace: WorkspacePort,
        output_projector: ToolOutputProjector | None = None,
    ) -> None:
        self._runtime = runtime
        self._workspace = workspace
        self._output_projector = output_projector

    @property
    def contract(self) -> ToolContract:
        return command_run_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        command = self._read_command_argument(tool_call.arguments["command"])
        cwd = self._read_cwd_argument(tool_call.arguments.get("cwd"))
        timeout_seconds = self._read_timeout_argument(tool_call.arguments.get("timeout_seconds"))

        request = RuntimeExecutionRequest(
            command=command,
            cwd=str(cwd),
            timeout_seconds=timeout_seconds,
        )
        runtime_result = self._runtime.execute(request)
        status = (
            ToolCallStatus.EXECUTED
            if runtime_result.succeeded
            else ToolCallStatus.FAILED
        )
        projected = (
            self._output_projector.project(
                stdout=runtime_result.stdout,
                stderr=runtime_result.stderr,
                artifact_name="command-run.txt",
            )
            if self._output_projector is not None
            else None
        )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=status,
            output=projected.model_output if projected is not None else runtime_result.stdout,
            metadata={
                "command": list(command),
                "cwd": str(Path(cwd).relative_to(self._workspace.root_path))
                if cwd != self._workspace.root_path
                else ".",
                "exit_code": runtime_result.exit_code,
                "stderr": "" if projected is not None else runtime_result.stderr,
                "timed_out": runtime_result.timed_out,
                **(projected.metadata if projected is not None else {}),
            },
        )

    def _read_cwd_argument(self, raw_cwd: object) -> Path:
        if raw_cwd is None:
            return self._workspace.root_path
        if not isinstance(raw_cwd, str):
            raise ToolArgumentError("command.run requires 'cwd' to be a string when provided")
        normalized_cwd = raw_cwd.strip()
        if not normalized_cwd:
            raise ToolArgumentError("command.run requires 'cwd' to be a non-blank string")
        try:
            return self._workspace.resolve_path(normalized_cwd)
        except ValueError as exc:
            raise ToolArgumentError("command.run 'cwd' must stay within the workspace") from exc

    @staticmethod
    def _read_command_argument(raw_command: object) -> tuple[str, ...]:
        invalid_shape_message = (
            "command.run requires 'command' to be a list or tuple of strings"
        )
        if isinstance(raw_command, str):
            raise ToolArgumentError(invalid_shape_message)
        if not isinstance(raw_command, list | tuple):
            raise ToolArgumentError(invalid_shape_message)
        normalized_command: list[str] = []
        for part in raw_command:
            if not isinstance(part, str):
                raise ToolArgumentError("command.run requires every command part to be a string")
            stripped = part.strip()
            if not stripped:
                raise ToolArgumentError("command.run does not allow blank command parts")
            normalized_command.append(stripped)
        if not normalized_command:
            raise ToolArgumentError("command.run requires at least one command part")
        return tuple(normalized_command)

    @staticmethod
    def _read_timeout_argument(raw_timeout: object) -> float | None:
        if raw_timeout is None:
            return None
        if not isinstance(raw_timeout, int | float) or isinstance(raw_timeout, bool):
            raise ToolArgumentError("command.run requires 'timeout_seconds' to be a number")
        timeout_seconds = float(raw_timeout)
        if timeout_seconds <= 0:
            raise ToolArgumentError("command.run requires 'timeout_seconds' to be positive")
        return timeout_seconds
