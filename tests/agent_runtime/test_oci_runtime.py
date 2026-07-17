from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest
from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeClass,
    RuntimeExecutionRequest,
    RuntimeLimits,
    SandboxSpec,
)
from agent_runtime import OciRuntime

IMAGE = "zebra/runtime@sha256:" + "a" * 64


class FakeEngine:
    def __init__(self, *, rootless: bool = True, runtimes: str = '{"runsc":{}}') -> None:
        self.rootless = rootless
        self.runtimes = runtimes
        self.calls: list[tuple[str, ...]] = []
        self.timeout_exec = False
        self.exec_stdout = "ok"
        self.containers = ""

    def __call__(self, command, **kwargs) -> CompletedProcess[str]:
        normalized = tuple(command)
        self.calls.append(normalized)
        if "version" in normalized:
            return CompletedProcess(normalized, 0, "26.1\n", "")
        if "info" in normalized and "{{json .Runtimes}}" in normalized:
            return CompletedProcess(normalized, 0, self.runtimes, "")
        if "info" in normalized:
            value = "true\n" if self.rootless else "false\n"
            return CompletedProcess(normalized, 0, value, "")
        if "create" in normalized:
            return CompletedProcess(normalized, 0, "container-1\n", "")
        if "ps" in normalized:
            return CompletedProcess(normalized, 0, self.containers, "")
        if "exec" in normalized and self.timeout_exec and "sleep" in normalized:
            raise TimeoutExpired(normalized, kwargs.get("timeout", 1), "partial", "late")
        if "exec" in normalized:
            return CompletedProcess(normalized, 0, self.exec_stdout, "")
        return CompletedProcess(normalized, 0, "", "")


def _spec(workspace: Path, runtime_class: RuntimeClass = RuntimeClass.GVISOR) -> SandboxSpec:
    return SandboxSpec(
        runtime_class=runtime_class,
        image=IMAGE,
        workspace_root=str(workspace),
        limits=RuntimeLimits(max_output_bytes=4),
    )


def test_gvisor_runtime_provisions_with_hardening_and_authority(tmp_path: Path) -> None:
    engine = FakeEngine()
    runtime = OciRuntime(_spec(tmp_path), runner=engine)

    handle = runtime.provision()

    create = next(call for call in engine.calls if "create" in call)
    for required in (
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "no-new-privileges",
        "--pids-limit",
        "--memory",
        "--cpus",
        "--user",
        "--tmpfs",
        "--runtime",
        "runsc",
    ):
        assert required in create
    assert handle.authority is not None
    assert handle.authority.runtime_class is RuntimeClass.GVISOR
    assert handle.authority.image == IMAGE
    assert handle.authority.network_enforcement == "container-network-none"


def test_runtime_fails_closed_without_required_isolation(tmp_path: Path) -> None:
    missing_runsc = OciRuntime(_spec(tmp_path), runner=FakeEngine(runtimes='{"evil-runsc":{}}'))
    rootful = OciRuntime(
        _spec(tmp_path, RuntimeClass.OCI_ROOTLESS),
        runner=FakeEngine(rootless=False),
    )

    with pytest.raises(RuntimeCapabilityError, match="does not advertise"):
        missing_runsc.provision()
    with pytest.raises(RuntimeCapabilityError, match="rootless"):
        rootful.provision()


def test_runtime_preserves_complete_output_for_artifact_projection(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    engine = FakeEngine()
    engine.exec_stdout = "abcdef"
    runtime = OciRuntime(_spec(tmp_path), runner=engine)
    runtime.provision()

    result = runtime.execute(
        RuntimeExecutionRequest(
            command=("python", "-V"),
            cwd=str(child),
        )
    )

    execute = next(call for call in engine.calls if "exec" in call and "python" in call)
    assert execute[execute.index("--workdir") + 1] == "/workspace/child"
    assert result.stdout == "abcdef"
    assert result.stdout_truncated is False


def test_runtime_timeout_destroys_container(tmp_path: Path) -> None:
    engine = FakeEngine()
    engine.timeout_exec = True
    runtime = OciRuntime(_spec(tmp_path), runner=engine)
    runtime.provision()

    result = runtime.execute(RuntimeExecutionRequest(command=("sleep", "60")))

    assert result.timed_out is True
    assert any("rm" in call and "--force" in call for call in engine.calls)


def test_runtime_rejects_escape_and_authority_drift(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = FakeEngine()
    runtime = OciRuntime(_spec(workspace), runner=engine, snapshot_root=tmp_path / "state")
    handle = runtime.provision()
    snapshot = runtime.snapshot(handle)

    with pytest.raises(RuntimeCapabilityError, match="stay within workspace"):
        runtime.execute(RuntimeExecutionRequest(command=("pwd",), cwd=str(tmp_path)))
    drifted = SandboxSpec(
        runtime_class=RuntimeClass.GVISOR,
        image=IMAGE,
        workspace_root=str(tmp_path / "restored-location"),
        limits=RuntimeLimits(memory_mb=1024),
    )
    other = OciRuntime(drifted, runner=engine, snapshot_root=tmp_path / "state")
    with pytest.raises(RuntimeCapabilityError, match="authority differs"):
        other.inspect_snapshot(snapshot)


def test_spec_digest_is_stable_across_restored_workspace_paths(tmp_path: Path) -> None:
    first = _spec(tmp_path / "one")
    second = _spec(tmp_path / "two")

    assert first.digest == second.digest
    assert (
        first.digest
        != SandboxSpec(
            runtime_class=RuntimeClass.GVISOR,
            image=IMAGE,
            workspace_root=str(tmp_path / "two"),
            engine="podman",
        ).digest
    )


def test_runtime_rejects_per_command_environment(tmp_path: Path) -> None:
    runtime = OciRuntime(_spec(tmp_path), runner=FakeEngine())

    with pytest.raises(RuntimeCapabilityError, match="per-command environment"):
        runtime.execute(RuntimeExecutionRequest(command=("env",), env={"TOKEN": "secret"}))


def test_runtime_cleans_stale_session_containers_by_label(tmp_path: Path) -> None:
    engine = FakeEngine()
    engine.containers = "stale-1\nstale-2\n"
    runtime = OciRuntime(_spec(tmp_path), runner=engine)

    removed = runtime.destroy_session("local-session")

    assert removed == 2
    listed = next(call for call in engine.calls if "ps" in call)
    assert "label=zebra.agent.session=local-session" in listed
    assert sum("rm" in call for call in engine.calls) == 2
