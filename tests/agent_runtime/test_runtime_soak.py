import json
import os
import platform
from pathlib import Path

import pytest
from agent_core.ports.runtime import RuntimeClass, RuntimeExecutionRequest, SandboxSpec
from agent_runtime import OsSandboxRuntime, os_sandbox_engine

_SOAK_ITERATIONS = 20


@pytest.mark.skipif(
    os.environ.get("ZEBRA_RUNTIME_SOAK") != "1",
    reason="runtime soak is opt-in",
)
def test_native_runtime_repeated_lifecycle_soak(tmp_path: Path) -> None:
    if platform.system() not in {"Darwin", "Linux"}:
        pytest.skip("native runtime soak supports Darwin and Linux")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = OsSandboxRuntime(
        SandboxSpec(
            runtime_class=RuntimeClass.OS_SANDBOX,
            image="",
            workspace_root=str(workspace),
            engine=os_sandbox_engine(),
        ),
        snapshot_root=tmp_path / "snapshots",
    )
    for iteration in range(_SOAK_ITERATIONS):
        handle = runtime.provision()
        result = runtime.execute(
            RuntimeExecutionRequest(
                command=("/bin/sh", "-c", f"printf {iteration} > cycle.txt")
            )
        )
        assert result.succeeded
        snapshot = runtime.snapshot(handle)
        assert runtime.inspect_snapshot(snapshot).restorable
        runtime.destroy(handle)
        runtime.cleanup_snapshot(snapshot)
    output = os.environ.get("ZEBRA_RUNTIME_EVIDENCE_PATH")
    if output:
        Path(output).write_text(
            json.dumps(
                {"iterations": _SOAK_ITERATIONS, "runtime": "os-sandbox", "failures": 0},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
