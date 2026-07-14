from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimePort
from agent_runtime.workspace import LocalWorkspace, WorkspacePathError

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

git_status_contract = ToolContract(
    name="git.status",
    description="Run a readonly git status inside the current workspace.",
    argument_properties={
        "cwd": {"type": "string", "description": "Optional workspace-relative directory."},
    },
)


class GitStatusTool:
    def __init__(self, runtime: RuntimePort, workspace: LocalWorkspace) -> None:
        self._runtime = runtime
        self._workspace = workspace

    @property
    def contract(self) -> ToolContract:
        return git_status_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        cwd = self._read_cwd_argument(tool_call.arguments.get("cwd"))
        runtime_result = self._runtime.execute(
            RuntimeExecutionRequest(
                command=("git", "status", "--short", "--branch"),
                cwd=str(cwd),
            )
        )
        status = ToolCallStatus.EXECUTED if runtime_result.succeeded else ToolCallStatus.FAILED
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=status,
            output=runtime_result.stdout,
            metadata={
                "cwd": str(Path(cwd).relative_to(self._workspace.layout.root_path))
                if cwd != self._workspace.layout.root_path
                else ".",
                "exit_code": runtime_result.exit_code,
                "stderr": runtime_result.stderr,
                "timed_out": runtime_result.timed_out,
            },
        )

    def _read_cwd_argument(self, raw_cwd: object) -> Path:
        if raw_cwd is None:
            return self._workspace.layout.root_path
        if not isinstance(raw_cwd, str):
            raise ToolArgumentError("git.status requires 'cwd' to be a string when provided")
        normalized_cwd = raw_cwd.strip()
        if not normalized_cwd:
            raise ToolArgumentError("git.status requires 'cwd' to be a non-blank string")
        try:
            return self._workspace.resolve_path(normalized_cwd)
        except WorkspacePathError as exc:
            raise ToolArgumentError("git.status 'cwd' must stay within the workspace") from exc
