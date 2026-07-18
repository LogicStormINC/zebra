import json
import os
import time
from pathlib import Path

import pytest
from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeExecutionRequest,
    RuntimeSnapshot,
)
from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.adapters.local_snapshot_state import LocalSnapshotStatus


def test_local_runtime_executes_successfully() -> None:
    runtime = LocalRuntime()

    result = runtime.execute(
        RuntimeExecutionRequest(
            command=(
                "python3",
                "-c",
                "print('runtime-ok')",
            )
        )
    )

    assert result.succeeded is True
    assert result.exit_code == 0
    assert result.stderr == ""
    assert "runtime-ok" in result.stdout


def test_local_runtime_captures_non_zero_exit() -> None:
    runtime = LocalRuntime()

    result = runtime.execute(
        RuntimeExecutionRequest(
            command=(
                "python3",
                "-c",
                "import sys; print('boom'); sys.exit(7)",
            )
        )
    )

    assert result.succeeded is False
    assert result.timed_out is False
    assert result.exit_code == 7
    assert "boom" in result.stdout
    assert result.failure_reason == "command_failed"


def test_local_runtime_reports_timeout() -> None:
    runtime = LocalRuntime()

    result = runtime.execute(
        RuntimeExecutionRequest(
            command=(
                "python3",
                "-c",
                "import time; print('start'); time.sleep(0.2); print('end')",
            ),
            timeout_seconds=0.05,
        )
    )

    assert result.succeeded is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.failure_reason == "timeout"


@pytest.mark.skipif(os.name != "posix", reason="process groups require POSIX")
def test_local_runtime_timeout_terminates_descendants(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    runtime = LocalRuntime()
    result = runtime.execute(
        RuntimeExecutionRequest(
            command=(
                "python3",
                "-c",
                (
                    "import pathlib,subprocess,time; "
                    f"p=subprocess.Popen(['sleep','30']); path=pathlib.Path({str(pid_file)!r}); "
                    "path.write_text(str(p.pid)); "
                    "time.sleep(30)"
                ),
            ),
            timeout_seconds=0.2,
        )
    )
    assert result.failure_reason == "timeout"
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("timed-out runtime left a descendant process alive")


def test_local_runtime_provision_suspend_and_resume_handle() -> None:
    runtime = LocalRuntime()

    handle = runtime.provision(workspace_root="/tmp/runtime-handle")
    suspended = runtime.suspend(handle)
    resumed = runtime.resume(suspended)

    assert handle.runtime_name == "local"
    assert handle.workspace_root == "/tmp/runtime-handle"
    assert handle.suspended is False
    assert suspended.suspended is True
    assert resumed.suspended is False
    assert resumed.handle_id == handle.handle_id


def test_local_runtime_snapshots_and_restores_workspace_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tracked_file = workspace / "note.txt"
    tracked_file.write_text("before-snapshot\n", encoding="utf-8")
    runtime = LocalRuntime(snapshot_root=tmp_path / "runtime-state")

    handle = runtime.provision(workspace_root=str(workspace))
    snapshot = runtime.snapshot(handle)
    tracked_file.write_text("after-snapshot\n", encoding="utf-8")

    restored = runtime.restore(snapshot)
    forked = runtime.fork(snapshot)

    assert snapshot.workspace_root == str(workspace.resolve())
    assert snapshot.snapshot_path is not None
    assert Path(snapshot.snapshot_path).is_dir()
    assert (
        json.loads((Path(snapshot.snapshot_path) / "manifest.json").read_text(encoding="utf-8"))[
            "source_handle_id"
        ]
        == handle.handle_id
    )
    assert restored.runtime_name == "local"
    assert restored.suspended is False
    assert restored.workspace_root is not None
    assert forked.workspace_root is not None
    assert Path(restored.workspace_root) != workspace.resolve()
    assert Path(forked.workspace_root) != workspace.resolve()
    restored_note = (Path(restored.workspace_root) / "note.txt").read_text(encoding="utf-8")
    forked_note = (Path(forked.workspace_root) / "note.txt").read_text(encoding="utf-8")
    assert restored_note == "before-snapshot\n"
    assert forked_note == "before-snapshot\n"


def test_local_runtime_snapshot_retention_prunes_old_snapshots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = LocalRuntime(
        snapshot_root=tmp_path / "runtime-state",
        snapshot_retention_limit=1,
    )

    handle = runtime.provision(workspace_root=str(workspace))
    first = runtime.snapshot(handle)
    second = runtime.snapshot(handle)

    assert first.snapshot_path is not None
    assert second.snapshot_path is not None
    assert Path(first.snapshot_path).exists() is False
    assert Path(second.snapshot_path).is_dir()
    inspection = runtime.inspect_snapshot(first)
    assert inspection.status is LocalSnapshotStatus.MISSING
    with pytest.raises(RuntimeCapabilityError, match="payload is unavailable"):
        runtime.restore(first)


def test_local_runtime_detects_incompatible_snapshot_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = LocalRuntime(snapshot_root=tmp_path / "runtime-state")

    handle = runtime.provision(workspace_root=str(workspace))
    snapshot = runtime.snapshot(handle)
    assert snapshot.snapshot_path is not None
    manifest_path = Path(snapshot.snapshot_path) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_name"] = "remote"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    inspection = runtime.inspect_snapshot(snapshot)

    assert inspection.status is LocalSnapshotStatus.INCOMPATIBLE
    assert inspection.restorable is False
    with pytest.raises(RuntimeCapabilityError, match="incompatible"):
        runtime.restore(snapshot)


def test_local_runtime_detects_tampered_snapshot_payload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("trusted", encoding="utf-8")
    runtime = LocalRuntime(snapshot_root=tmp_path / "runtime-state")
    snapshot = runtime.snapshot(runtime.provision(workspace_root=str(workspace)))
    assert snapshot.snapshot_path is not None
    (Path(snapshot.snapshot_path) / "workspace" / "note.txt").write_text(
        "tampered", encoding="utf-8"
    )

    inspection = runtime.inspect_snapshot(snapshot)

    assert inspection.status is LocalSnapshotStatus.INCOMPATIBLE
    with pytest.raises(RuntimeCapabilityError, match="payload digest"):
        runtime.restore(snapshot)


def test_local_runtime_cleanup_snapshot_removes_payload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = LocalRuntime(snapshot_root=tmp_path / "runtime-state")

    handle = runtime.provision(workspace_root=str(workspace))
    snapshot = runtime.snapshot(handle)
    assert snapshot.snapshot_path is not None

    cleanup = runtime.cleanup_snapshot(snapshot)
    inspection = runtime.inspect_snapshot(snapshot)

    assert cleanup.removed is True
    assert cleanup.status is LocalSnapshotStatus.VALID
    assert Path(snapshot.snapshot_path).exists() is False
    assert inspection.status is LocalSnapshotStatus.MISSING


def test_local_runtime_rejects_snapshot_operations_outside_supported_subset(
    tmp_path: Path,
) -> None:
    runtime = LocalRuntime(snapshot_root=tmp_path / "runtime-state")
    handle = runtime.provision()
    snapshot = RuntimeSnapshot.create(
        runtime_name="remote",
        source_handle_id="remote-handle",
    )

    with pytest.raises(RuntimeCapabilityError, match="workspace_root-backed handle"):
        runtime.snapshot(handle)
    with pytest.raises(RuntimeCapabilityError, match="does not belong to local runtime"):
        runtime.restore(snapshot)
    with pytest.raises(RuntimeCapabilityError, match="does not belong to local runtime"):
        runtime.fork(snapshot)


def test_local_runtime_rejects_snapshot_backend_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = LocalRuntime(snapshot_root=workspace / ".runtime-state")
    handle = runtime.provision(workspace_root=str(workspace))

    with pytest.raises(RuntimeCapabilityError, match="must not be inside"):
        runtime.snapshot(handle)


def test_local_runtime_snapshot_preserves_external_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("host-secret", encoding="utf-8")
    (workspace / "external-link").symlink_to(secret)
    runtime = LocalRuntime(snapshot_root=tmp_path / "state")

    snapshot = runtime.snapshot(runtime.provision(workspace_root=str(workspace)))

    assert snapshot.snapshot_path is not None
    copied = Path(snapshot.snapshot_path) / "workspace" / "external-link"
    assert copied.is_symlink()
    assert copied.readlink() == secret


def test_local_runtime_rejects_snapshot_path_outside_backend(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = LocalRuntime(snapshot_root=tmp_path / "state")
    snapshot = runtime.snapshot(runtime.provision(workspace_root=str(workspace)))
    forged = RuntimeSnapshot(
        snapshot_id=snapshot.snapshot_id,
        runtime_name=snapshot.runtime_name,
        source_handle_id=snapshot.source_handle_id,
        created_at=snapshot.created_at,
        workspace_root=snapshot.workspace_root,
        snapshot_path=str(tmp_path),
    )

    with pytest.raises(RuntimeCapabilityError, match="incompatible"):
        runtime.restore(forged)
