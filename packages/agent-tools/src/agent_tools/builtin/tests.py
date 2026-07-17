from collections.abc import Mapping
from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimePort
from agent_core.ports.workspace import WorkspacePort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError
from agent_tools.output_projection import ToolOutputProjector

tests_run_contract = ToolContract(
    name="tests.run",
    required_arguments=("preset",),
    description="Run a predefined validation command inside the current workspace.",
    argument_properties={
        "preset": {"type": "string", "description": "Configured validation preset name."},
        "cwd": {"type": "string", "description": "Optional workspace-relative directory."},
        "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
    },
)


class TestsRunTool:
    __test__ = False

    def __init__(
        self,
        runtime: RuntimePort,
        workspace: WorkspacePort,
        presets: Mapping[str, tuple[str, ...]],
        output_projector: ToolOutputProjector | None = None,
    ) -> None:
        if not presets:
            raise ValueError("tests.run requires at least one preset")
        self._runtime = runtime
        self._workspace = workspace
        self._presets = dict(presets)
        self._output_projector = output_projector

    @property
    def contract(self) -> ToolContract:
        return tests_run_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        preset_name = self._read_preset_argument(tool_call)
        cwd = self._read_cwd_argument(tool_call.arguments.get("cwd"))
        timeout_seconds = self._read_timeout_argument(tool_call.arguments.get("timeout_seconds"))

        try:
            command = self._presets[preset_name]
        except KeyError as exc:
            raise ToolArgumentError(f"tests.run preset is not defined: {preset_name}") from exc

        runtime_result = self._runtime.execute(
            RuntimeExecutionRequest(
                command=command,
                cwd=str(cwd),
                timeout_seconds=timeout_seconds,
            )
        )
        status = ToolCallStatus.EXECUTED if runtime_result.succeeded else ToolCallStatus.FAILED
        projected = (
            self._output_projector.project(
                stdout=runtime_result.stdout,
                stderr=runtime_result.stderr,
                artifact_name=f"tests-{preset_name}.txt",
            )
            if self._output_projector is not None
            else None
        )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=status,
            output=projected.model_output if projected is not None else runtime_result.stdout,
            metadata={
                "preset": preset_name,
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

    def _read_preset_argument(self, tool_call: ToolCall) -> str:
        raw_preset = tool_call.arguments["preset"]
        if not isinstance(raw_preset, str):
            raise ToolArgumentError("tests.run requires 'preset' to be a string")
        normalized_preset = raw_preset.strip()
        if not normalized_preset:
            raise ToolArgumentError("tests.run requires 'preset' to be a non-blank string")
        return normalized_preset

    def _read_cwd_argument(self, raw_cwd: object) -> Path:
        if raw_cwd is None:
            return self._workspace.root_path
        if not isinstance(raw_cwd, str):
            raise ToolArgumentError("tests.run requires 'cwd' to be a string when provided")
        normalized_cwd = raw_cwd.strip()
        if not normalized_cwd:
            raise ToolArgumentError("tests.run requires 'cwd' to be a non-blank string")
        try:
            return self._workspace.resolve_path(normalized_cwd)
        except ValueError as exc:
            raise ToolArgumentError("tests.run 'cwd' must stay within the workspace") from exc

    @staticmethod
    def _read_timeout_argument(raw_timeout: object) -> float | None:
        if raw_timeout is None:
            return None
        if not isinstance(raw_timeout, int | float) or isinstance(raw_timeout, bool):
            raise ToolArgumentError("tests.run requires 'timeout_seconds' to be a number")
        timeout_seconds = float(raw_timeout)
        if timeout_seconds <= 0:
            raise ToolArgumentError("tests.run requires 'timeout_seconds' to be positive")
        return timeout_seconds
