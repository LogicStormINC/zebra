import json
from pathlib import Path

import pytest
from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeExecutionRequest,
    RuntimeSnapshot,
)
from agent_runtime.adapters.local import LocalRuntime


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
    assert json.loads((Path(snapshot.snapshot_path) / "manifest.json").read_text(encoding="utf-8"))[
        "source_handle_id"
    ] == handle.handle_id
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
    with pytest.raises(RuntimeCapabilityError, match="no longer available"):
        runtime.restore(first)


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
