from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeExecutionRequest,
    RuntimeHandle,
    RuntimePort,
    RuntimeSnapshot,
)
from agent_security import SetupDownload, SetupDownloadEvidence, SetupEgressGateway


class SetupPhaseError(RuntimeError):
    """Raised when Setup cannot hand a verified workspace to Agent execution."""


@dataclass(frozen=True)
class SetupPhasePlan:
    command: tuple[str, ...]
    dependencies: tuple[SetupDownload, ...]
    lockfiles: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.command or not self.command[0].strip():
            raise ValueError("setup command must not be empty")
        if not self.dependencies:
            raise ValueError("setup phase requires at least one pinned dependency")
        if not self.lockfiles:
            raise ValueError("setup phase requires at least one lockfile")
        for lockfile in self.lockfiles:
            path = Path(lockfile)
            if path.is_absolute() or ".." in path.parts or not lockfile.strip():
                raise ValueError("setup lockfiles must be relative workspace paths")


@dataclass(frozen=True)
class SetupPhaseResult:
    agent_handle: RuntimeHandle
    snapshot: RuntimeSnapshot
    artifact_payload: bytes
    downloads: tuple[SetupDownloadEvidence, ...]
    lockfile_hashes: dict[str, str]
    credential_revoked: bool


class SetupPhaseRunner:
    def __init__(self, plan: SetupPhasePlan, gateway: SetupEgressGateway) -> None:
        self._plan = plan
        self._gateway = gateway

    def run(self, runtime: RuntimePort, *, workspace_root: Path) -> SetupPhaseResult:
        workspace = workspace_root.expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise SetupPhaseError("setup workspace must be a directory")
        before = _lockfile_hashes(workspace, self._plan.lockfiles)
        downloads: list[SetupDownloadEvidence] = []
        try:
            for dependency in self._plan.dependencies:
                downloads.append(self._gateway.materialize(dependency))
        finally:
            self._gateway.close()
        if not self._gateway.credential_revoked:
            raise SetupPhaseError("temporary setup credential was not revoked")

        setup_handle: RuntimeHandle | None = None
        try:
            setup_handle = runtime.provision(workspace_root=str(workspace))
            _require_no_network_authority(setup_handle)
            execution = runtime.execute(
                RuntimeExecutionRequest(
                    command=self._plan.command,
                    cwd=str(workspace),
                )
            )
            if not execution.succeeded:
                detail = (execution.stderr or execution.stdout).strip()[:2048]
                raise SetupPhaseError("setup command failed" + (f": {detail}" if detail else ""))
            after = _lockfile_hashes(workspace, self._plan.lockfiles)
            if after != before:
                raise SetupPhaseError("setup command changed a locked dependency manifest")
            snapshot = runtime.snapshot(setup_handle)
            inspection = runtime.inspect_snapshot(snapshot)
            if not inspection.restorable:
                raise SetupPhaseError(
                    "setup snapshot is not restorable: " + ", ".join(inspection.problems)
                )
            runtime.destroy(setup_handle)
            setup_handle = None
            agent_handle = runtime.provision(workspace_root=str(workspace))
            _require_no_network_authority(agent_handle)
        except Exception:
            if setup_handle is not None:
                runtime.destroy(setup_handle)
            raise

        artifact = _artifact_payload(
            plan=self._plan,
            snapshot=snapshot,
            downloads=tuple(downloads),
            lockfile_hashes=after,
            authority_digest=(
                agent_handle.authority.spec_digest
                if agent_handle.authority is not None
                else None
            ),
        )
        return SetupPhaseResult(
            agent_handle=agent_handle,
            snapshot=snapshot,
            artifact_payload=artifact,
            downloads=tuple(downloads),
            lockfile_hashes=after,
            credential_revoked=True,
        )


def _require_no_network_authority(handle: RuntimeHandle) -> None:
    authority = handle.authority
    if authority is None:
        raise RuntimeCapabilityError("setup phase requires a hard runtime authority")
    if authority.network_enforcement not in {
        "container-network-none",
        "os-sandbox-network-deny",
    }:
        raise RuntimeCapabilityError("setup and agent sandboxes must enforce no network")


def _lockfile_hashes(workspace: Path, lockfiles: tuple[str, ...]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in lockfiles:
        path = (workspace / relative).resolve(strict=True)
        try:
            path.relative_to(workspace)
        except ValueError as exc:
            raise SetupPhaseError("setup lockfile escapes workspace") from exc
        if not path.is_file():
            raise SetupPhaseError(f"setup lockfile is not a file: {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _artifact_payload(
    *,
    plan: SetupPhasePlan,
    snapshot: RuntimeSnapshot,
    downloads: tuple[SetupDownloadEvidence, ...],
    lockfile_hashes: dict[str, str],
    authority_digest: str | None,
) -> bytes:
    command_digest = hashlib.sha256(
        json.dumps(plan.command, separators=(",", ":")).encode()
    ).hexdigest()
    payload = {
        "schema_version": "zebra.runtime.setup.v1",
        "command_sha256": command_digest,
        "credential_revoked": True,
        "network_enforcement": "none",
        "runtime_authority_digest": authority_digest,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_authority_digest": snapshot.authority_digest,
        "lockfiles": lockfile_hashes,
        "downloads": [asdict(download) for download in downloads],
        "sbom": {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [
                {
                    "SPDXID": f"SPDXRef-Download-{index}",
                    "downloadLocation": download.url,
                    "checksums": [{"algorithm": "SHA256", "checksumValue": download.sha256}],
                    "fileName": download.file_name,
                }
                for index, download in enumerate(downloads, start=1)
            ],
        },
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
