import re
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimePort
from agent_core.ports.workspace import WorkspacePort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

patch_apply_contract = ToolContract(
    name="patch.apply",
    required_arguments=("patch",),
    description="Apply a constrained unified diff inside the current workspace.",
    argument_properties={
        "patch": {"type": "string", "description": "Unified diff to apply."},
    },
)


class PatchApplyTool:
    def __init__(self, runtime: RuntimePort, workspace: WorkspacePort) -> None:
        self._runtime = runtime
        self._workspace = workspace

    @property
    def contract(self) -> ToolContract:
        return patch_apply_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        patch_text = self._normalize_patch_headers(self._read_patch_argument(tool_call))
        self._validate_patch_paths(patch_text)
        hunk_error = self._hunk_count_error(patch_text)
        if hunk_error is not None:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output="",
                metadata={
                    "exit_code": None,
                    "stderr": hunk_error,
                    "timed_out": False,
                    "failure_reason": "invalid_hunk_counts",
                },
            )

        self._workspace.ensure()
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._workspace.root_path,
            prefix=".agent-patch-",
            suffix=".diff",
            delete=False,
        ) as patch_file:
            patch_file.write(patch_text)
            patch_path = Path(patch_file.name)

        try:
            runtime_result = self._runtime.execute(
                RuntimeExecutionRequest(
                    command=("patch", "--batch", "-p0", "-i", str(patch_path)),
                    cwd=str(self._workspace.root_path),
                )
            )
        finally:
            patch_path.unlink(missing_ok=True)

        status = ToolCallStatus.EXECUTED if runtime_result.succeeded else ToolCallStatus.FAILED
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=status,
            output=runtime_result.stdout,
            metadata={
                "exit_code": runtime_result.exit_code,
                "stderr": runtime_result.stderr,
                "timed_out": runtime_result.timed_out,
                "failure_reason": runtime_result.failure_reason,
            },
        )

    def _validate_patch_paths(self, patch_text: str) -> None:
        for line in patch_text.splitlines():
            if line.startswith("--- ") or line.startswith("+++ "):
                raw_path = line[4:].strip()
                if raw_path == "/dev/null":
                    continue
                normalized = self._normalize_patch_path(raw_path)
                try:
                    self._workspace.resolve_path(normalized)
                except ValueError as exc:
                    raise ToolArgumentError(
                        "patch.apply contains a path outside the workspace"
                    ) from exc

    @staticmethod
    def _hunk_count_error(patch_text: str) -> str | None:
        expected: tuple[int, int] | None = None
        observed_old = observed_new = 0

        def mismatch() -> bool:
            return expected is not None and expected != (observed_old, observed_new)

        for line in patch_text.splitlines():
            if line.startswith("@@"):
                if mismatch():
                    return "patch.apply hunk line counts do not match the header"
                match = re.match(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
                if match is None:
                    return "patch.apply hunk header is malformed"
                old_count, new_count = (
                    int(value) if value is not None else 1 for value in match.groups()
                )
                expected = (old_count, new_count)
                observed_old = observed_new = 0
                continue
            if expected is None or line.startswith("\\ No newline at end of file"):
                continue
            if line.startswith(" "):
                observed_old += 1
                observed_new += 1
            elif line.startswith("-"):
                observed_old += 1
            elif line.startswith("+"):
                observed_new += 1
        if mismatch():
            return "patch.apply hunk line counts do not match the header"
        return None

    @staticmethod
    def _normalize_patch_path(raw_path: str) -> str:
        path_token = raw_path.split("\t", maxsplit=1)[0].strip()
        if path_token.startswith("a/") or path_token.startswith("b/"):
            path_token = path_token[2:]
        normalized = PurePosixPath(path_token)
        if normalized.is_absolute():
            raise ToolArgumentError("patch.apply does not allow absolute paths")
        return normalized.as_posix()

    @classmethod
    def _normalize_patch_headers(cls, patch_text: str) -> str:
        lines = []
        for line in patch_text.splitlines():
            if line.startswith("--- ") or line.startswith("+++ "):
                prefix, raw_path = line[:4], line[4:]
                path_token, separator, suffix = raw_path.partition("\t")
                if path_token.strip() != "/dev/null":
                    path_token = cls._normalize_patch_path(path_token)
                line = prefix + path_token + (separator + suffix if separator else "")
            lines.append(line)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _read_patch_argument(tool_call: ToolCall) -> str:
        raw_patch = tool_call.arguments["patch"]
        if not isinstance(raw_patch, str):
            raise ToolArgumentError("patch.apply requires 'patch' to be a string")
        normalized_patch = raw_patch.strip()
        if not normalized_patch:
            raise ToolArgumentError("patch.apply requires 'patch' to be a non-blank string")
        return normalized_patch + "\n"
