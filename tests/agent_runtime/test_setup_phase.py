import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from agent_core.ports.runtime import RuntimeCapabilityError, RuntimeClass, SandboxSpec
from agent_runtime import (
    LocalRuntime,
    OsSandboxRuntime,
    SetupPhaseError,
    SetupPhasePlan,
    SetupPhaseRunner,
)
from agent_security import SetupDownload, SetupEgressGateway, TemporarySetupCredential


class FakeSandboxRunner:
    def __init__(self, *, mutation: Path | None = None) -> None:
        self.mutation = mutation

    def __call__(self, command, **kwargs) -> CompletedProcess[str]:
        normalized = tuple(command)
        if normalized[-1] not in {"/usr/bin/true", "/bin/true"} and self.mutation:
            self.mutation.write_text("changed", encoding="utf-8")
        return CompletedProcess(normalized, 0, "ok", "")


def _plan(payload: bytes) -> SetupPhasePlan:
    return SetupPhasePlan(
        command=("/bin/sh", "-c", "test -f .zebra/setup-cache/package.whl"),
        dependencies=(
            SetupDownload(
                url="https://files.example.test/package.whl",
                sha256=hashlib.sha256(payload).hexdigest(),
                file_name="package.whl",
            ),
        ),
        lockfiles=("uv.lock",),
    )


def _runtime(workspace: Path, state: Path, runner=None) -> OsSandboxRuntime:
    return OsSandboxRuntime(
        SandboxSpec(
            runtime_class=RuntimeClass.OS_SANDBOX,
            image="",
            workspace_root=str(workspace),
            engine="sandbox-exec",
        ),
        system="Darwin",
        finder=lambda _: "/usr/bin/sandbox-exec",
        runner=runner or FakeSandboxRunner(),
        snapshot_root=state,
    )


def test_setup_phase_revokes_credential_before_verified_snapshot_handoff(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "uv.lock").write_text("locked", encoding="utf-8")
    credential = TemporarySetupCredential("temporary-secret")
    gateway = SetupEgressGateway(
        allowed_domains=("files.example.test",),
        cache_root=workspace / ".zebra" / "setup-cache",
        credential=credential,
        transport=lambda *args, **kwargs: b"wheel",
    )

    result = SetupPhaseRunner(_plan(b"wheel"), gateway).run(
        _runtime(workspace, tmp_path / "state"),
        workspace_root=workspace,
    )

    assert result.credential_revoked and credential.revoked
    assert result.agent_handle.handle_id != result.snapshot.source_handle_id
    assert result.agent_handle.authority is not None
    assert result.agent_handle.authority.network_enforcement == "os-sandbox-network-deny"
    artifact = json.loads(result.artifact_payload)
    assert artifact["credential_revoked"] is True
    assert artifact["network_enforcement"] == "none"
    assert artifact["sbom"]["spdxVersion"] == "SPDX-2.3"
    assert artifact["snapshot_id"] == result.snapshot.snapshot_id
    assert "temporary-secret" not in result.artifact_payload.decode()
    assert (workspace / ".zebra" / "setup-cache" / "package.whl").read_bytes() == b"wheel"


def test_setup_phase_rejects_lockfile_mutation_and_still_revokes_credential(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lockfile = workspace / "uv.lock"
    lockfile.write_text("locked", encoding="utf-8")
    credential = TemporarySetupCredential("temporary-secret")
    gateway = SetupEgressGateway(
        allowed_domains=("files.example.test",),
        cache_root=workspace / ".zebra" / "setup-cache",
        credential=credential,
        transport=lambda *args, **kwargs: b"wheel",
    )

    with pytest.raises(SetupPhaseError, match="changed a locked"):
        SetupPhaseRunner(_plan(b"wheel"), gateway).run(
            _runtime(workspace, tmp_path / "state", FakeSandboxRunner(mutation=lockfile)),
            workspace_root=workspace,
        )

    assert credential.revoked


def test_setup_phase_rejects_trusted_runtime_even_after_verified_download(
    tmp_path: Path,
) -> None:
    (tmp_path / "uv.lock").write_text("locked", encoding="utf-8")
    gateway = SetupEgressGateway(
        allowed_domains=("files.example.test",),
        cache_root=tmp_path / ".zebra" / "setup-cache",
        transport=lambda *args, **kwargs: b"wheel",
    )

    with pytest.raises(RuntimeCapabilityError, match="hard runtime"):
        SetupPhaseRunner(_plan(b"wheel"), gateway).run(
            LocalRuntime(snapshot_root=tmp_path / "state"),
            workspace_root=tmp_path,
        )
