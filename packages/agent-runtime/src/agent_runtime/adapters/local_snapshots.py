import json
from collections import defaultdict
from pathlib import Path
from shutil import copytree, rmtree
from tempfile import mkdtemp

from agent_core.ports.runtime import RuntimeCapabilityError, RuntimeHandle, RuntimeSnapshot


class LocalSnapshotBackend:
    def __init__(
        self,
        *,
        root_path: str | Path | None = None,
        retention_limit: int = 3,
    ) -> None:
        if retention_limit <= 0:
            raise ValueError("retention_limit must be positive")

        base_root = (
            Path(root_path).expanduser()
            if root_path is not None
            else Path(mkdtemp(prefix="zebra-agent-runtime-"))
        )
        self._root = base_root.resolve(strict=False)
        self._snapshots_root = self._root / "snapshots"
        self._restores_root = self._root / "restores"
        self._retention_limit = retention_limit
        self._restored_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._snapshots_by_handle: dict[str, list[Path]] = defaultdict(list)
        self._ensure_layout()

    def create_snapshot(self, handle: RuntimeHandle) -> RuntimeSnapshot:
        workspace_root = self._require_workspace_root(handle)
        snapshot = RuntimeSnapshot.create(
            runtime_name=handle.runtime_name,
            source_handle_id=handle.handle_id,
            workspace_root=str(workspace_root),
        )
        snapshot_root = self._snapshots_root / snapshot.snapshot_id
        snapshot_root.mkdir(parents=True, exist_ok=False)
        snapshot_workspace = snapshot_root / "workspace"
        copytree(workspace_root, snapshot_workspace)
        self._write_manifest(snapshot_root, snapshot, workspace_root)
        stored_snapshot = RuntimeSnapshot(
            snapshot_id=snapshot.snapshot_id,
            runtime_name=snapshot.runtime_name,
            source_handle_id=snapshot.source_handle_id,
            created_at=snapshot.created_at,
            workspace_root=snapshot.workspace_root,
            snapshot_path=str(snapshot_root),
        )
        tracked = self._snapshots_by_handle[handle.handle_id]
        tracked.append(snapshot_root)
        self._apply_retention(tracked)
        return stored_snapshot

    def restore_handle(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        snapshot_root = self._require_snapshot_root(snapshot)
        workspace_root = self._require_snapshot_workspace(snapshot_root)
        restore_root = self._allocate_restore_root(snapshot.snapshot_id, "restore")
        copytree(workspace_root, restore_root)
        return RuntimeHandle.create(
            runtime_name=snapshot.runtime_name,
            workspace_root=str(restore_root),
        )

    def fork_handle(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        snapshot_root = self._require_snapshot_root(snapshot)
        workspace_root = self._require_snapshot_workspace(snapshot_root)
        fork_root = self._allocate_restore_root(snapshot.snapshot_id, "fork")
        copytree(workspace_root, fork_root)
        return RuntimeHandle.create(
            runtime_name=snapshot.runtime_name,
            workspace_root=str(fork_root),
        )

    def _allocate_restore_root(self, snapshot_id: str, operation: str) -> Path:
        key = (snapshot_id, operation)
        self._restored_counts[key] += 1
        return self._restores_root / f"{snapshot_id}-{operation}-{self._restored_counts[key]:02d}"

    def _apply_retention(self, snapshot_paths: list[Path]) -> None:
        overflow = len(snapshot_paths) - self._retention_limit
        if overflow <= 0:
            return
        for expired in snapshot_paths[:overflow]:
            rmtree(expired, ignore_errors=True)
        del snapshot_paths[:overflow]

    def _ensure_layout(self) -> None:
        self._snapshots_root.mkdir(parents=True, exist_ok=True)
        self._restores_root.mkdir(parents=True, exist_ok=True)

    def _require_workspace_root(self, handle: RuntimeHandle) -> Path:
        if handle.workspace_root is None or not handle.workspace_root.strip():
            raise RuntimeCapabilityError(
                "local runtime snapshot requires a workspace_root-backed handle"
            )
        workspace_root = Path(handle.workspace_root).expanduser().resolve(strict=False)
        if not workspace_root.exists():
            raise RuntimeCapabilityError("local runtime snapshot workspace_root does not exist")
        if not workspace_root.is_dir():
            raise RuntimeCapabilityError(
                "local runtime snapshot workspace_root must be a directory"
            )
        return workspace_root

    def _require_snapshot_root(self, snapshot: RuntimeSnapshot) -> Path:
        if snapshot.snapshot_path is None or not snapshot.snapshot_path.strip():
            raise RuntimeCapabilityError("local runtime snapshot is missing snapshot_path")
        snapshot_root = Path(snapshot.snapshot_path).expanduser().resolve(strict=False)
        if not snapshot_root.exists():
            raise RuntimeCapabilityError("local runtime snapshot is no longer available")
        if not snapshot_root.is_dir():
            raise RuntimeCapabilityError("local runtime snapshot path must be a directory")
        return snapshot_root

    def _require_snapshot_workspace(self, snapshot_root: Path) -> Path:
        workspace_root = snapshot_root / "workspace"
        if not workspace_root.exists() or not workspace_root.is_dir():
            raise RuntimeCapabilityError("local runtime snapshot workspace payload is unavailable")
        return workspace_root

    def _write_manifest(
        self,
        snapshot_root: Path,
        snapshot: RuntimeSnapshot,
        workspace_root: Path,
    ) -> None:
        manifest = {
            "snapshot_id": snapshot.snapshot_id,
            "runtime_name": snapshot.runtime_name,
            "source_handle_id": snapshot.source_handle_id,
            "created_at": snapshot.created_at.isoformat(),
            "workspace_root": str(workspace_root),
        }
        (snapshot_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
