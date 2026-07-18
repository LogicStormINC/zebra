import os
import platform
from pathlib import Path

import pytest
from agent_core.ports.runtime import RuntimeClass, RuntimeExecutionRequest, SandboxSpec
from agent_runtime import OsSandboxRuntime, os_sandbox_engine


@pytest.mark.skipif(
    os.environ.get("ZEBRA_OS_SANDBOX_SMOKE") != "1",
    reason="real OS sandbox smoke is opt-in",
)
def test_real_os_sandbox_blocks_host_escape_network_and_inherits_to_children(
    tmp_path: Path,
) -> None:
    if platform.system() not in {"Darwin", "Linux"}:
        pytest.skip("OS sandbox smoke supports Darwin and Linux")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    outside = tmp_path / "outside.txt"
    inside.write_text("inside", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    runtime = OsSandboxRuntime(
        SandboxSpec(
            runtime_class=RuntimeClass.OS_SANDBOX,
            image="",
            workspace_root=str(workspace),
            engine=os_sandbox_engine(),
        )
    )
    runtime.provision()

    readable = runtime.execute(RuntimeExecutionRequest(command=("/bin/cat", str(inside))))
    child_escape = runtime.execute(
        RuntimeExecutionRequest(command=("/bin/sh", "-c", f"/bin/cat {outside}"))
    )
    write_inside = runtime.execute(
        RuntimeExecutionRequest(command=("/bin/sh", "-c", "echo ok > created.txt"))
    )
    runtime.execute(
        RuntimeExecutionRequest(command=("/bin/sh", "-c", f"echo bad > {outside}"))
    )
    outside_after = runtime.execute(RuntimeExecutionRequest(command=("/bin/cat", str(outside))))
    network = runtime.execute(
        RuntimeExecutionRequest(
            command=("/usr/bin/curl", "--connect-timeout", "1", "http://1.1.1.1")
        )
    )

    assert readable.stdout == "inside"
    assert child_escape.succeeded is False
    assert write_inside.succeeded and (workspace / "created.txt").read_text().strip() == "ok"
    assert outside.read_text(encoding="utf-8") == "outside"
    assert outside_after.succeeded is False
    assert network.succeeded is False
