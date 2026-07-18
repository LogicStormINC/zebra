from pathlib import Path
from subprocess import CompletedProcess

import pytest
from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeClass,
    RuntimeExecutionRequest,
    SandboxSpec,
)
from agent_runtime import OsSandboxRuntime


class FakeRunner:
    def __init__(self, *, probe_succeeds: bool = True) -> None:
        self.probe_succeeds = probe_succeeds
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command, **kwargs) -> CompletedProcess[str]:
        normalized = tuple(command)
        self.calls.append(normalized)
        is_probe = normalized[-1] in {"/usr/bin/true", "/bin/true"}
        if is_probe and not self.probe_succeeds:
            return CompletedProcess(normalized, 1, "", "sandbox unavailable")
        return CompletedProcess(normalized, 0, "ok", "")


def _spec(workspace: Path, engine: str) -> SandboxSpec:
    return SandboxSpec(
        runtime_class=RuntimeClass.OS_SANDBOX,
        image="",
        workspace_root=str(workspace),
        engine=engine,
    )


def test_seatbelt_runtime_provisions_truthful_authority_and_sanitizes_env(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runtime = OsSandboxRuntime(
        _spec(tmp_path, "sandbox-exec"),
        system="Darwin",
        finder=lambda _: "/usr/bin/sandbox-exec",
        runner=runner,
    )

    handle = runtime.provision()
    result = runtime.execute(RuntimeExecutionRequest(command=("/bin/sh", "-c", "pwd")))

    assert result.succeeded
    assert handle.authority is not None
    assert handle.authority.runtime_class is RuntimeClass.OS_SANDBOX
    assert handle.authority.engine == "/usr/bin/sandbox-exec"
    assert handle.authority.network_enforcement == "os-sandbox-network-deny"
    execute = runner.calls[-1]
    assert execute[:2] == ("/usr/bin/sandbox-exec", "-p")
    assert "(deny network*)" in execute[2]
    assert f'(subpath "{tmp_path}")' in execute[2]
    assert execute[3:5] == ("/usr/bin/env", "-i")
    assert not any("SECRET" in part for part in execute)


def test_bubblewrap_command_uses_private_namespaces_and_workspace_only(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runtime = OsSandboxRuntime(
        _spec(tmp_path, "bwrap"),
        system="Linux",
        finder=lambda _: "/usr/bin/bwrap",
        runner=runner,
    )
    runtime.provision()

    runtime.execute(RuntimeExecutionRequest(command=("/bin/sh", "-c", "true")))

    execute = runner.calls[-1]
    for expected in (
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--tmpfs",
        "--clearenv",
        "--bind",
    ):
        assert expected in execute
    bind_index = execute.index("--bind")
    assert execute[bind_index + 1 : bind_index + 3] == (str(tmp_path), str(tmp_path))
    assert execute[-3:] == ("/bin/sh", "-c", "true")


@pytest.mark.parametrize(
    ("system", "engine"),
    [("Darwin", "sandbox-exec"), ("Linux", "bwrap")],
)
def test_runtime_fails_closed_when_platform_boundary_is_missing_or_broken(
    tmp_path: Path,
    system: str,
    engine: str,
) -> None:
    missing = OsSandboxRuntime(
        _spec(tmp_path, engine),
        system=system,
        finder=lambda _: None,
    )
    broken = OsSandboxRuntime(
        _spec(tmp_path, engine),
        system=system,
        finder=lambda _: f"/usr/bin/{engine}",
        runner=FakeRunner(probe_succeeds=False),
    )

    with pytest.raises(RuntimeCapabilityError, match="missing"):
        missing.provision()
    with pytest.raises(RuntimeCapabilityError, match="probe failed"):
        broken.provision()


def test_runtime_rejects_environment_cwd_escape_and_authority_drift(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = OsSandboxRuntime(
        _spec(workspace, "sandbox-exec"),
        system="Darwin",
        finder=lambda _: "/usr/bin/sandbox-exec",
        runner=FakeRunner(),
        snapshot_root=tmp_path / "snapshots",
    )
    handle = runtime.provision()
    snapshot = runtime.snapshot(handle)

    with pytest.raises(RuntimeCapabilityError, match="environment variables"):
        runtime.execute(RuntimeExecutionRequest(command=("env",), env={"TOKEN": "secret"}))
    with pytest.raises(RuntimeCapabilityError, match="stay within workspace"):
        runtime.execute(RuntimeExecutionRequest(command=("pwd",), cwd=str(tmp_path)))
    drifted = OsSandboxRuntime(
        SandboxSpec(
            runtime_class=RuntimeClass.OS_SANDBOX,
            image="",
            workspace_root=str(workspace),
            engine="sandbox-exec",
            workspace_writable=False,
        ),
        system="Darwin",
        finder=lambda _: "/usr/bin/sandbox-exec",
        runner=FakeRunner(),
        snapshot_root=tmp_path / "snapshots",
    )
    with pytest.raises(RuntimeCapabilityError, match="authority differs"):
        drifted.inspect_snapshot(snapshot)


def test_os_sandbox_rejects_wrong_platform_and_oci_constructor(tmp_path: Path) -> None:
    with pytest.raises(RuntimeCapabilityError, match="unsupported"):
        OsSandboxRuntime(_spec(tmp_path, "unsupported"), system="Windows")
