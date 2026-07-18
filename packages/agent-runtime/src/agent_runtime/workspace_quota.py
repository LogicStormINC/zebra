from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path

from agent_core.ports.runtime import RuntimeCapabilityError


class WorkspaceQuotaError(RuntimeCapabilityError):
    pass


@dataclass(frozen=True)
class WorkspaceQuotaEvidence:
    workspace_root: str
    mount_point: str
    filesystem: str
    capacity_bytes: int
    maximum_bytes: int


def require_workspace_quota(
    workspace_root: str | Path,
    *,
    maximum_bytes: int,
    system: str | None = None,
    mountinfo_path: str | Path = "/proc/self/mountinfo",
) -> WorkspaceQuotaEvidence:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise WorkspaceQuotaError("workspace quota root must be a directory")
    if maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be positive")
    current_system = system or platform.system()
    mount_point, filesystem = _mount_for(root, current_system, Path(mountinfo_path))
    if mount_point != root:
        raise WorkspaceQuotaError(
            "workspace quota requires the workspace root to be a dedicated mount point"
        )
    stats = os.statvfs(root)
    capacity_bytes = stats.f_blocks * stats.f_frsize
    if capacity_bytes > maximum_bytes:
        raise WorkspaceQuotaError(
            f"workspace filesystem capacity {capacity_bytes} exceeds quota {maximum_bytes}"
        )
    return WorkspaceQuotaEvidence(
        workspace_root=str(root),
        mount_point=str(mount_point),
        filesystem=filesystem,
        capacity_bytes=capacity_bytes,
        maximum_bytes=maximum_bytes,
    )


def _mount_for(root: Path, system: str, mountinfo_path: Path) -> tuple[Path, str]:
    if system == "Linux":
        return _linux_mount_for(root, mountinfo_path)
    if system == "Darwin":
        return _darwin_mount_for(root)
    raise WorkspaceQuotaError(f"workspace quota inspection is unsupported on {system}")


def _linux_mount_for(root: Path, mountinfo_path: Path) -> tuple[Path, str]:
    candidates: list[tuple[Path, str]] = []
    try:
        lines = mountinfo_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise WorkspaceQuotaError("cannot inspect workspace filesystem mount") from exc
    for line in lines:
        before, separator, after = line.partition(" - ")
        fields = before.split()
        after_fields = after.split()
        if not separator or len(fields) < 5 or not after_fields:
            continue
        mount_point = Path(_unescape_mount(fields[4])).resolve()
        if root == mount_point or mount_point in root.parents:
            candidates.append((mount_point, after_fields[0]))
    if not candidates:
        raise WorkspaceQuotaError("workspace filesystem mount is not present in mountinfo")
    return max(candidates, key=lambda item: len(item[0].parts))


def _darwin_mount_for(root: Path) -> tuple[Path, str]:
    from subprocess import run

    completed = run(
        ("/bin/df", "-P", str(root)),
        capture_output=True,
        text=True,
        check=False,
    )
    lines = completed.stdout.splitlines()
    if completed.returncode != 0 or len(lines) < 2:
        raise WorkspaceQuotaError("cannot inspect workspace filesystem mount")
    fields = lines[-1].split(maxsplit=5)
    if len(fields) < 6:
        raise WorkspaceQuotaError("workspace filesystem report is malformed")
    return Path(fields[-1]).resolve(), "darwin-volume"


def _unescape_mount(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )
