import os
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_runtime import WorkspaceQuotaError, require_workspace_quota


def _mountinfo(path: Path, mount_point: Path) -> Path:
    escaped = str(mount_point).replace(" ", "\\040")
    path.write_text(
        f"36 25 0:32 / {escaped} rw,relatime - tmpfs tmpfs rw,size=8388608\n",
        encoding="utf-8",
    )
    return path


def test_linux_workspace_quota_requires_dedicated_capacity_limited_mount(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mountinfo = _mountinfo(tmp_path / "mountinfo", workspace)
    stats = os.statvfs(workspace)

    with patch("agent_runtime.workspace_quota.os.statvfs", return_value=stats):
        evidence = require_workspace_quota(
            workspace,
            maximum_bytes=stats.f_blocks * stats.f_frsize,
            system="Linux",
            mountinfo_path=mountinfo,
        )

    assert evidence.mount_point == str(workspace)
    assert evidence.filesystem == "tmpfs"


def test_workspace_quota_rejects_shared_or_oversized_filesystem(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shared = _mountinfo(tmp_path / "shared", tmp_path)
    dedicated = _mountinfo(tmp_path / "dedicated", workspace)
    stats = os.statvfs(workspace)

    with pytest.raises(WorkspaceQuotaError, match="dedicated mount"):
        require_workspace_quota(
            workspace,
            maximum_bytes=stats.f_blocks * stats.f_frsize,
            system="Linux",
            mountinfo_path=shared,
        )
    with (
        patch("agent_runtime.workspace_quota.os.statvfs", return_value=stats),
        pytest.raises(WorkspaceQuotaError, match="exceeds quota"),
    ):
        require_workspace_quota(
            workspace,
            maximum_bytes=stats.f_blocks * stats.f_frsize - 1,
            system="Linux",
            mountinfo_path=dedicated,
        )


def test_workspace_quota_fails_closed_on_unsupported_platform(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceQuotaError, match="unsupported"):
        require_workspace_quota(tmp_path, maximum_bytes=1024, system="Windows")
