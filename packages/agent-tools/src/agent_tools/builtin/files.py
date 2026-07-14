from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_runtime.workspace import LocalWorkspace, WorkspacePathError

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

file_read_contract = ToolContract(
    name="files.read",
    required_arguments=("path",),
    description="Read a file from the current workspace.",
    argument_properties={
        "path": {"type": "string", "description": "Workspace-relative file path."},
    },
)


class FileReadTool:
    def __init__(self, workspace: LocalWorkspace, *, max_bytes: int = 16_384) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._workspace = workspace
        self._max_bytes = max_bytes

    @property
    def contract(self) -> ToolContract:
        return file_read_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        relative_path = self._read_path_argument(tool_call)

        try:
            target_path = self._workspace.resolve_path(relative_path)
        except WorkspacePathError as exc:
            return self._failure(tool_call, reason="path_outside_workspace", detail=str(exc))

        if not target_path.exists():
            return self._failure(tool_call, reason="file_not_found", detail=str(target_path))
        if not target_path.is_file():
            return self._failure(tool_call, reason="not_a_file", detail=str(target_path))

        content = target_path.read_bytes()
        truncated = len(content) > self._max_bytes
        visible = content[: self._max_bytes].decode("utf-8", errors="replace")
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=visible,
            metadata={
                "path": str(Path(relative_path)),
                "byte_count": len(content),
                "truncated": truncated,
            },
        )

    def _read_path_argument(self, tool_call: ToolCall) -> str:
        raw_path = tool_call.arguments["path"]
        if not isinstance(raw_path, str):
            raise ToolArgumentError("files.read requires 'path' to be a string")
        normalized_path = raw_path.strip()
        if not normalized_path:
            raise ToolArgumentError("files.read requires 'path' to be a non-blank string")
        return normalized_path

    @staticmethod
    def _failure(tool_call: ToolCall, *, reason: str, detail: str) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            output="",
            metadata={
                "reason": reason,
                "detail": detail,
            },
        )
