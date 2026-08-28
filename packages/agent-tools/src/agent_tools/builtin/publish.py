from __future__ import annotations

import mimetypes
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult, ToolRisk
from agent_core.ports.workspace import WorkspacePort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

FilePublisher = Callable[[bytes, str, str], str]

file_publish_contract = ToolContract(
    name="files.publish",
    required_arguments=("path",),
    description="Publish a generated workspace file as a downloadable user artifact.",
    argument_properties={
        "path": {"type": "string", "description": "Workspace-relative file path."},
        "display_name": {"type": "string", "description": "Optional download file name."},
    },
    risk=ToolRisk.WRITE,
)


class FilePublishTool:
    def __init__(
        self,
        workspace: WorkspacePort,
        publish: FilePublisher,
        *,
        max_bytes: int,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._workspace = workspace
        self._publish = publish
        self._max_bytes = max_bytes

    @property
    def contract(self) -> ToolContract:
        return file_publish_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        relative_path = _required_text(tool_call.arguments.get("path"), "path")
        if _contains_symlink(self._workspace.root_path, relative_path):
            return _failure(tool_call, "symlink_not_allowed", relative_path)
        try:
            target = self._workspace.resolve_path(relative_path)
        except ValueError as exc:
            return _failure(tool_call, "path_outside_workspace", str(exc))
        if target.is_symlink():
            return _failure(tool_call, "symlink_not_allowed", relative_path)
        if not target.exists():
            return _failure(tool_call, "file_not_found", relative_path)
        if not target.is_file():
            return _failure(tool_call, "not_a_file", relative_path)
        size = target.stat().st_size
        if size > self._max_bytes:
            return _failure(tool_call, "file_too_large", f"{size}>{self._max_bytes}")
        file_name = _safe_file_name(tool_call.arguments.get("display_name"), target.name)
        payload = target.read_bytes()
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        uri = self._publish(payload, file_name, mime_type)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"Published {file_name}: {uri}",
            metadata={
                "artifact_uri": uri,
                "delivery": True,
                "file_name": file_name,
                "mime_type": mime_type,
                "sha256": sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            },
        )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError(f"files.publish requires '{field_name}' to be a string")
    return value.strip()


def _safe_file_name(value: object, fallback: str) -> str:
    name = fallback if value is None else _required_text(value, "display_name")
    if Path(name).name != name or name in {".", ".."} or any(char in name for char in "\r\n\0"):
        raise ToolArgumentError("files.publish display_name must be a safe basename")
    if len(name) > 255:
        raise ToolArgumentError("files.publish display_name is too long")
    return name


def _failure(tool_call: ToolCall, reason: str, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output="",
        metadata={"reason": reason, "detail": detail},
    )


def _contains_symlink(root: Path, relative_path: str) -> bool:
    current = root
    for part in Path(relative_path).parts:
        current /= part
        if current.is_symlink():
            return True
    return False
