import os
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_runtime.workspace import LocalWorkspace, WorkspacePathError

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

MAX_LIMIT = 100
MAX_OFFSET = 10_000
MAX_QUERY_LENGTH = 512
MAX_GLOB_LENGTH = 256
MAX_SCANNED_FILES = 20_000
MAX_FILE_BYTES = 1_048_576
MAX_LINE_CHARS = 500
MAX_OUTPUT_BYTES = 32_768
MAX_MATCHES = MAX_OFFSET + MAX_LIMIT + 1

files_search_contract = ToolContract(
    name="files.search",
    parallel_safe=True,
    required_arguments=("query",),
    description="Search filenames or text within bounded workspace files.",
    argument_properties={
        "query": {"type": "string", "description": "Literal text to find."},
        "mode": {
            "type": "string",
            "enum": ["content", "files"],
            "description": "Search file contents or workspace-relative filenames.",
        },
        "path": {"type": "string", "description": "Workspace-relative directory root."},
        "glob": {"type": "string", "description": "Optional file glob such as **/*.py."},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
        "offset": {"type": "integer", "minimum": 0, "maximum": MAX_OFFSET},
    },
)


class WorkspaceSearchTool:
    def __init__(self, workspace: LocalWorkspace) -> None:
        self._workspace = workspace

    @property
    def contract(self) -> ToolContract:
        return files_search_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        query = _string_argument(tool_call, "query", required=True, max_length=MAX_QUERY_LENGTH)
        mode = _mode_argument(tool_call.arguments.get("mode"))
        path = _string_argument(tool_call, "path", default=".", max_length=MAX_GLOB_LENGTH)
        glob = _string_argument(
            tool_call, "glob", default=None, max_length=MAX_GLOB_LENGTH
        )
        limit = _integer_argument(tool_call, "limit", default=50, minimum=1, maximum=MAX_LIMIT)
        offset = _integer_argument(
            tool_call, "offset", default=0, minimum=0, maximum=MAX_OFFSET
        )
        assert query is not None
        assert path is not None

        if any(part.startswith(".") and part not in {".", ".."} for part in Path(path).parts):
            return _failure(tool_call, "hidden_path", "search roots must not be hidden")

        try:
            root = self._workspace.resolve_path(path)
        except WorkspacePathError as exc:
            return _failure(tool_call, "path_outside_workspace", str(exc))
        if not root.exists():
            return _failure(tool_call, "path_not_found", path)
        if not root.is_dir():
            return _failure(tool_call, "not_a_directory", path)

        matches, scanned_files, scan_truncated = self._find_matches(
            root=root,
            query=query,
            mode=mode,
            glob=glob,
        )
        page, output_truncated = _bounded_page(matches, offset=offset, limit=limit)
        returned_count = len(page)
        has_more = offset + returned_count < len(matches) or scan_truncated
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="\n".join(page),
            metadata={
                "mode": mode,
                "query": query,
                "path": _relative_path(root, self._workspace.layout.root_path),
                "glob": glob,
                "match_count": len(matches),
                "returned_count": returned_count,
                "scanned_files": scanned_files,
                "offset": offset,
                "truncated": has_more or output_truncated,
                "next_offset": offset + returned_count if has_more or output_truncated else None,
                "hint": "Narrow query, path, or glob, or continue from next_offset."
                if has_more or output_truncated
                else None,
            },
        )

    def _find_matches(
        self,
        *,
        root: Path,
        query: str,
        mode: str,
        glob: str | None,
    ) -> tuple[list[str], int, bool]:
        matches: list[str] = []
        scanned_files = 0
        scan_truncated = False
        for candidate in _workspace_files(root):
            if scanned_files >= MAX_SCANNED_FILES:
                scan_truncated = True
                break
            if len(matches) >= MAX_MATCHES:
                scan_truncated = True
                break
            scanned_files += 1
            relative = candidate.relative_to(self._workspace.layout.root_path).as_posix()
            root_relative = candidate.relative_to(root).as_posix()
            if glob is not None and not fnmatch(root_relative, glob):
                continue
            if mode == "files":
                if query in relative:
                    matches.append(relative)
                continue
            matches.extend(
                _content_matches(
                    candidate,
                    relative,
                    query,
                    limit=MAX_MATCHES - len(matches),
                )
            )
        return matches, scanned_files, scan_truncated


def _workspace_files(root: Path) -> Iterator[Path]:
    for directory, directory_names, filenames in os.walk(root, followlinks=False):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not name.startswith(".") and not (Path(directory) / name).is_symlink()
        )
        for filename in sorted(name for name in filenames if not name.startswith(".")):
            path = Path(directory) / filename
            if path.is_file() and not path.is_symlink():
                yield path


def _content_matches(path: Path, relative: str, query: str, *, limit: int) -> list[str]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        content = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in content:
        return []
    results: list[str] = []
    for line_number, line in enumerate(content.decode("utf-8", errors="replace").splitlines(), 1):
        column = line.find(query)
        if column >= 0:
            visible = line[:MAX_LINE_CHARS]
            results.append(f"{relative}:{line_number}:{column + 1}:{visible}")
            if len(results) >= limit:
                break
    return results


def _bounded_page(matches: list[str], *, offset: int, limit: int) -> tuple[list[str], bool]:
    page: list[str] = []
    byte_count = 0
    output_truncated = False
    for match in matches[offset : offset + limit]:
        item_bytes = len(match.encode("utf-8")) + (1 if page else 0)
        if byte_count + item_bytes > MAX_OUTPUT_BYTES:
            output_truncated = True
            break
        page.append(match)
        byte_count += item_bytes
    return page, output_truncated


def _string_argument(
    tool_call: ToolCall,
    name: str,
    *,
    max_length: int,
    required: bool = False,
    default: str | None = None,
) -> str | None:
    raw = tool_call.arguments.get(name)
    if raw is None:
        if required:
            raise ToolArgumentError(f"files.search requires '{name}'")
        return default
    if not isinstance(raw, str):
        raise ToolArgumentError(f"files.search requires '{name}' to be a string")
    value = raw.strip()
    if not value:
        raise ToolArgumentError(f"files.search requires '{name}' to be non-blank")
    if len(value) > max_length:
        raise ToolArgumentError(f"files.search '{name}' exceeds {max_length} characters")
    return value


def _mode_argument(raw: object) -> str:
    if raw is None:
        return "content"
    if not isinstance(raw, str) or raw not in {"content", "files"}:
        raise ToolArgumentError("files.search 'mode' must be 'content' or 'files'")
    return raw


def _integer_argument(
    tool_call: ToolCall,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = tool_call.arguments.get(name, default)
    if not isinstance(raw, int) or isinstance(raw, bool) or not minimum <= raw <= maximum:
        raise ToolArgumentError(
            f"files.search '{name}' must be an integer from {minimum} to {maximum}"
        )
    return raw


def _relative_path(path: Path, workspace_root: Path) -> str:
    relative = path.relative_to(workspace_root).as_posix()
    return relative or "."


def _failure(tool_call: ToolCall, reason: str, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output="",
        metadata={"reason": reason, "detail": detail},
    )
