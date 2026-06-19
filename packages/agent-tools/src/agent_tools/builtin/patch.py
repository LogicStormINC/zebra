from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimePort
from agent_runtime.workspace import LocalWorkspace, WorkspacePathError

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

patch_apply_contract = ToolContract(
    name="patch.apply",
    required_arguments=("patch",),
    description="Apply a constrained unified diff inside the current workspace.",
)


class PatchApplyTool:
    def __init__(self, runtime: RuntimePort, workspace: LocalWorkspace) -> None:
        self._runtime = runtime
        self._workspace = workspace

    @property
    def contract(self) -> ToolContract:
        return patch_apply_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        patch_text = self._read_patch_argument(tool_call)
        self._validate_patch_paths(patch_text)

        self._workspace.ensure()
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._workspace.layout.root_path,
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
                    cwd=str(self._workspace.layout.root_path),
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
                except WorkspacePathError as exc:
                    raise ToolArgumentError(
                        "patch.apply contains a path outside the workspace"
                    ) from exc

    @staticmethod
    def _normalize_patch_path(raw_path: str) -> str:
        path_token = raw_path.split("\t", maxsplit=1)[0].strip()
        if path_token.startswith("a/") or path_token.startswith("b/"):
            path_token = path_token[2:]
        normalized = PurePosixPath(path_token)
        if normalized.is_absolute():
            raise ToolArgumentError("patch.apply does not allow absolute paths")
        return normalized.as_posix()

    @staticmethod
    def _read_patch_argument(tool_call: ToolCall) -> str:
        raw_patch = tool_call.arguments["patch"]
        if not isinstance(raw_patch, str):
            raise ToolArgumentError("patch.apply requires 'patch' to be a string")
        normalized_patch = raw_patch.strip()
        if not normalized_patch:
            raise ToolArgumentError("patch.apply requires 'patch' to be a non-blank string")
        return normalized_patch + "\n"
