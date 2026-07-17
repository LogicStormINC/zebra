import os
from pathlib import Path

import pytest
from agent_core.ports.runtime import RuntimeClass, RuntimeExecutionRequest, SandboxSpec
from agent_runtime import OciRuntime


@pytest.mark.skipif(
    os.environ.get("ZEBRA_GVISOR_SMOKE") != "1",
    reason="requires a Linux Docker engine configured with runsc",
)
def test_real_gvisor_runtime_enforces_workspace_and_network(tmp_path: Path) -> None:
    image = os.environ["ZEBRA_GVISOR_IMAGE"]
    runtime = OciRuntime(
        SandboxSpec(
            runtime_class=RuntimeClass.GVISOR,
            image=image,
            workspace_root=str(tmp_path),
            container_uid=os.getuid(),
            container_gid=os.getgid(),
        )
    )

    handle = runtime.provision()
    try:
        write = runtime.execute(
            RuntimeExecutionRequest(command=("/bin/sh", "-c", "printf runtime-ok > proof.txt"))
        )
        network = runtime.execute(
            RuntimeExecutionRequest(
                command=(
                    "/bin/sh",
                    "-c",
                    "wget -q -T 3 -O - https://example.com",
                )
            )
        )
        socket = runtime.execute(
            RuntimeExecutionRequest(command=("/bin/sh", "-c", "test ! -e /var/run/docker.sock"))
        )
        privilege = runtime.execute(
            RuntimeExecutionRequest(
                command=(
                    "/bin/sh",
                    "-c",
                    'test "$(id -u)" -ne 0 && '
                    "test \"$(awk '/CapEff/ {print $2}' /proc/self/status)\" = "
                    '"0000000000000000" && ! touch /runtime-root-proof',
                )
            )
        )
    finally:
        runtime.destroy(handle)

    assert write.succeeded is True
    assert (tmp_path / "proof.txt").read_text(encoding="utf-8") == "runtime-ok"
    assert network.succeeded is False
    assert socket.succeeded is True
    assert privilege.succeeded is True
