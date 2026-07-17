from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.workspace import WorkspacePort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

MAX_DEPTH = 4
MAX_LIMIT = 200
MAX_OFFSET = 10_000
MAX_SCANNED_ENTRIES = 10_000
MAX_OUTPUT_BYTES = 32_768
_DEFAULT_OUTPUT_LIMIT = object()
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)

files_list_contract = ToolContract(
    name="files.list",
    parallel_safe=True,
    description="List a bounded directory or shallow tree inside the current workspace.",
    argument_properties={
        "path": {"type": "string", "description": "Workspace-relative directory root."},
        "depth": {"type": "integer", "minimum": 1, "maximum": MAX_DEPTH},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
        "offset": {"type": "integer", "minimum": 0, "maximum": MAX_OFFSET},
    },
)


@dataclass(frozen=True)
class _Entry:
    path: str
    kind: str
    size: int | None


class WorkspaceListTool:
    def __init__(
        self,
        workspace: WorkspacePort,
        *,
        max_output_bytes: int | None | object = _DEFAULT_OUTPUT_LIMIT,
    ) -> None:
        if max_output_bytes is _DEFAULT_OUTPUT_LIMIT:
            max_output_bytes = MAX_OUTPUT_BYTES
        assert isinstance(max_output_bytes, int) or max_output_bytes is None
        if max_output_bytes is not None and max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._workspace = workspace
        self._max_output_bytes = max_output_bytes

    @property
    def contract(self) -> ToolContract:
        return files_list_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        arguments = tool_call.arguments
        unknown = set(arguments) - {"path", "depth", "limit", "offset"}
        if unknown:
            raise ToolArgumentError("files.list contains unsupported arguments")
        path = _path_argument(arguments.get("path", "."))
        depth = _integer_argument(arguments.get("depth", 1), "depth", 1, MAX_DEPTH)
        limit = _integer_argument(arguments.get("limit", 100), "limit", 1, MAX_LIMIT)
        offset = _integer_argument(arguments.get("offset", 0), "offset", 0, MAX_OFFSET)

        path_error = self._validate_path(path)
        if path_error is not None:
            return _failure(tool_call, *path_error)
        try:
            root = self._workspace.resolve_path(path)
        except ValueError as exc:
            return _failure(tool_call, "path_outside_workspace", str(exc))
        if not root.exists():
            return _failure(tool_call, "path_not_found", path)
        if not root.is_dir():
            return _failure(tool_call, "not_a_directory", path)

        entries, scanned_entries, scan_truncated = _inventory(
            root,
            workspace_root=self._workspace.root_path,
            depth=depth,
        )
        output_path = _relative(root, self._workspace.root_path)
        page, output_truncated = _page(
            entries,
            output_path=output_path,
            offset=offset,
            limit=limit,
            max_output_bytes=self._max_output_bytes,
        )
        known_more = offset + len(page) < len(entries)
        truncated = scan_truncated or known_more or output_truncated
        payload = {
            "path": output_path,
            "entries": [entry.__dict__ for entry in page],
        }
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "path": payload["path"],
                "depth": depth,
                "scanned_entries": scanned_entries,
                "matched_entries": len(entries),
                "returned_count": len(page),
                "offset": offset,
                "next_offset": offset + len(page) if known_more or output_truncated else None,
                "truncated": truncated,
                "scan_truncated": scan_truncated,
                "output_truncated": output_truncated,
            },
        )

    def _validate_path(self, path: str) -> tuple[str, str] | None:
        candidate = Path(path)
        if candidate.is_absolute():
            return "path_outside_workspace", "workspace paths must be relative"
        if ".." in candidate.parts:
            return "path_outside_workspace", "workspace paths must not contain traversal"
        visible_parts = tuple(part for part in candidate.parts if part != ".")
        if any(part.startswith(".") for part in visible_parts):
            return "hidden_path", "directory roots must not be hidden"
        current = self._workspace.root_path
        for part in visible_parts:
            current /= part
            if current.is_symlink():
                return "symlink_path", "directory roots must not contain symlinks"
        return None


def _inventory(
    root: Path, *, workspace_root: Path, depth: int
) -> tuple[list[_Entry], int, bool]:
    entries: list[_Entry] = []
    scanned_entries = 0
    scan_truncated = False
    pending: list[tuple[Path, int]] = [(root, 1)]
    while pending:
        directory, level = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            continue
        child_directories: list[Path] = []
        for child in children:
            if scanned_entries >= MAX_SCANNED_ENTRIES:
                scan_truncated = True
                break
            scanned_entries += 1
            if _excluded(child):
                continue
            if child.is_dir():
                entries.append(_Entry(_relative(child, workspace_root), "directory", None))
                if level < depth:
                    child_directories.append(child)
            elif child.is_file():
                try:
                    size = child.stat().st_size
                except OSError:
                    continue
                entries.append(_Entry(_relative(child, workspace_root), "file", size))
        if scan_truncated:
            break
        pending.extend((child, level + 1) for child in reversed(child_directories))
    entries.sort(key=lambda entry: (entry.kind != "directory", entry.path.casefold(), entry.path))
    return entries, scanned_entries, scan_truncated


def _page(
    entries: list[_Entry],
    *,
    output_path: str,
    offset: int,
    limit: int,
    max_output_bytes: int | None,
) -> tuple[list[_Entry], bool]:
    page: list[_Entry] = []
    for entry in entries[offset : offset + limit]:
        candidate = page + [entry]
        payload = json.dumps(
            {"path": output_path, "entries": [item.__dict__ for item in candidate]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if max_output_bytes is not None and len(payload.encode("utf-8")) > max_output_bytes:
            return page, True
        page.append(entry)
    return page, False


def _excluded(path: Path) -> bool:
    return (
        path.name.startswith(".")
        or path.is_symlink()
        or (path.is_dir() and path.name in EXCLUDED_DIRECTORY_NAMES)
    )


def _path_argument(raw: object) -> str:
    if not isinstance(raw, str):
        raise ToolArgumentError("files.list requires 'path' to be a string")
    value = raw.strip()
    if not value:
        raise ToolArgumentError("files.list requires 'path' to be non-blank")
    return value


def _integer_argument(raw: object, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or not minimum <= raw <= maximum:
        raise ToolArgumentError(
            f"files.list '{name}' must be an integer from {minimum} to {maximum}"
        )
    return raw


def _relative(path: Path, workspace_root: Path) -> str:
    relative = path.relative_to(workspace_root).as_posix()
    return relative or "."


def _failure(tool_call: ToolCall, reason: str, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output="",
        metadata={"reason": reason, "detail": detail},
    )
