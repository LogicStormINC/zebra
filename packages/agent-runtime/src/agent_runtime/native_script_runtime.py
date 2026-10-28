"""One invocation owns its dedicated runtime and empty mount lifecycle."""

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_core.domain.native_script import NativeScript
from agent_core.domain.native_script_protocol import ScriptRunResult
from agent_core.domain.script_bundle import ScriptRunnerProfile
from agent_core.ports.runtime import RuntimePort, SandboxSpec

from agent_runtime.native_script import NativeScriptRunner


class ScopedNativeScriptRunner:
    def __init__(
        self,
        profile: ScriptRunnerProfile,
        factory: Callable[[Path], tuple[RuntimePort, SandboxSpec]],
        *,
        workspace_parent: Path | None = None,
    ) -> None:
        self._profile, self._factory = profile, factory
        self._workspace_parent = workspace_parent

    def run(
        self,
        script: NativeScript,
        raw_invocation: bytes,
        *,
        cancellation_check: Callable[[], None] | None = None,
    ) -> ScriptRunResult:
        with TemporaryDirectory(prefix="native-script-", dir=self._workspace_parent) as directory:
            # Seatbelt must read the actual Python installation; no business workspace is mounted.
            workspace = (
                Path(self._profile.python).resolve(strict=True).parent.parent
                if self._profile.runtime_class == "os-sandbox"
                else Path(directory)
            )
            runtime, spec = self._factory(workspace)
            return NativeScriptRunner(runtime, spec, python=self._profile.python).run(
                script,
                raw_invocation,
                cancellation_check=cancellation_check,
            )
