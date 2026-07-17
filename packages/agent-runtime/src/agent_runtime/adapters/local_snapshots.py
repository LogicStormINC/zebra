import json
import os
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from shutil import copytree, rmtree
from tempfile import mkdtemp

from agent_core.ports.runtime import RuntimeCapabilityError, RuntimeHandle, RuntimeSnapshot

from agent_runtime.adapters.local_snapshot_state import (
    LocalSnapshotCleanupResult,
    LocalSnapshotInspection,
    LocalSnapshotStatus,
)


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
        if self._root.is_relative_to(workspace_root):
            raise RuntimeCapabilityError("runtime snapshot root must not be inside the workspace")
        snapshot = RuntimeSnapshot.create(
            runtime_name=handle.runtime_name,
            source_handle_id=handle.handle_id,
            workspace_root=str(workspace_root),
            authority_digest=(
                handle.authority.spec_digest if handle.authority is not None else None
            ),
            image=handle.authority.image if handle.authority is not None else None,
        )
        snapshot_root = self._snapshots_root / snapshot.snapshot_id
        snapshot_root.mkdir(parents=True, exist_ok=False)
        snapshot_workspace = snapshot_root / "workspace"
        copytree(workspace_root, snapshot_workspace, symlinks=True)
        self._write_manifest(snapshot_root, snapshot, workspace_root)
        stored_snapshot = RuntimeSnapshot(
            snapshot_id=snapshot.snapshot_id,
            runtime_name=snapshot.runtime_name,
            source_handle_id=snapshot.source_handle_id,
            created_at=snapshot.created_at,
            workspace_root=snapshot.workspace_root,
            snapshot_path=str(snapshot_root),
            authority_digest=snapshot.authority_digest,
            image=snapshot.image,
        )
        tracked = self._snapshots_by_handle[handle.handle_id]
        tracked.append(snapshot_root)
        self._apply_retention(tracked)
        return stored_snapshot

    def inspect_snapshot(self, snapshot: RuntimeSnapshot) -> LocalSnapshotInspection:
        snapshot_root = self._snapshot_root_path(snapshot)
        if snapshot_root is None:
            return LocalSnapshotInspection(
                snapshot_id=snapshot.snapshot_id,
                snapshot_path=snapshot.snapshot_path,
                status=LocalSnapshotStatus.INCOMPATIBLE,
                problems=("snapshot_path is missing",),
            )
        if not snapshot_root.exists():
            return LocalSnapshotInspection(
                snapshot_id=snapshot.snapshot_id,
                snapshot_path=str(snapshot_root),
                status=LocalSnapshotStatus.MISSING,
                problems=("snapshot root is no longer available",),
            )
        if not snapshot_root.is_dir():
            return LocalSnapshotInspection(
                snapshot_id=snapshot.snapshot_id,
                snapshot_path=str(snapshot_root),
                status=LocalSnapshotStatus.INCOMPATIBLE,
                problems=("snapshot path must be a directory",),
            )
        manifest = self._load_manifest(snapshot_root)
        if manifest is None:
            return LocalSnapshotInspection(
                snapshot_id=snapshot.snapshot_id,
                snapshot_path=str(snapshot_root),
                status=LocalSnapshotStatus.MISSING,
                problems=("manifest.json is unavailable",),
            )
        workspace_root = snapshot_root / "workspace"
        if not workspace_root.exists() or not workspace_root.is_dir():
            return LocalSnapshotInspection(
                snapshot_id=snapshot.snapshot_id,
                snapshot_path=str(snapshot_root),
                status=LocalSnapshotStatus.MISSING,
                problems=("workspace payload is unavailable",),
            )
        problems = self._manifest_problems(snapshot, manifest, workspace_root)
        if problems:
            return LocalSnapshotInspection(
                snapshot_id=snapshot.snapshot_id,
                snapshot_path=str(snapshot_root),
                status=LocalSnapshotStatus.INCOMPATIBLE,
                problems=problems,
            )
        return LocalSnapshotInspection(
            snapshot_id=snapshot.snapshot_id,
            snapshot_path=str(snapshot_root),
            status=LocalSnapshotStatus.VALID,
        )

    def cleanup_snapshot(self, snapshot: RuntimeSnapshot) -> LocalSnapshotCleanupResult:
        inspection = self.inspect_snapshot(snapshot)
        snapshot_root = self._snapshot_root_path(snapshot)
        removed = False
        if snapshot_root is not None and snapshot_root.exists() and snapshot_root.is_dir():
            rmtree(snapshot_root, ignore_errors=False)
            self._forget_snapshot_path(snapshot_root)
            removed = True
        return LocalSnapshotCleanupResult(
            snapshot_id=snapshot.snapshot_id,
            snapshot_path=inspection.snapshot_path,
            status=inspection.status,
            removed=removed,
            problems=inspection.problems,
        )

    def restore_handle(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        snapshot_root = self._require_restorable_snapshot(snapshot)
        workspace_root = snapshot_root / "workspace"
        restore_root = self._allocate_restore_root(snapshot.snapshot_id, "restore")
        copytree(workspace_root, restore_root, symlinks=True)
        return RuntimeHandle.create(
            runtime_name=snapshot.runtime_name,
            workspace_root=str(restore_root),
        )

    def fork_handle(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        snapshot_root = self._require_restorable_snapshot(snapshot)
        workspace_root = snapshot_root / "workspace"
        fork_root = self._allocate_restore_root(snapshot.snapshot_id, "fork")
        copytree(workspace_root, fork_root, symlinks=True)
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

    def _require_restorable_snapshot(self, snapshot: RuntimeSnapshot) -> Path:
        inspection = self.inspect_snapshot(snapshot)
        if inspection.status is LocalSnapshotStatus.MISSING:
            raise RuntimeCapabilityError(
                "local runtime snapshot payload is unavailable: " + ", ".join(inspection.problems)
            )
        if inspection.status is LocalSnapshotStatus.INCOMPATIBLE:
            raise RuntimeCapabilityError(
                "local runtime snapshot is incompatible: " + ", ".join(inspection.problems)
            )
        if inspection.snapshot_path is None:
            raise RuntimeCapabilityError("local runtime snapshot is missing snapshot_path")
        return Path(inspection.snapshot_path).expanduser().resolve(strict=False)

    def _snapshot_root_path(self, snapshot: RuntimeSnapshot) -> Path | None:
        if snapshot.snapshot_path is None or not snapshot.snapshot_path.strip():
            return None
        candidate = Path(snapshot.snapshot_path).expanduser().resolve(strict=False)
        expected = (self._snapshots_root / snapshot.snapshot_id).resolve(strict=False)
        return candidate if candidate == expected else None

    def _load_manifest(self, snapshot_root: Path) -> dict[str, object] | None:
        manifest_path = snapshot_root / "manifest.json"
        if not manifest_path.exists() or not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"__decode_error__": str(exc)}
        if not isinstance(manifest, dict):
            return {"__shape_error__": "manifest root must be an object"}
        return manifest

    def _manifest_problems(
        self,
        snapshot: RuntimeSnapshot,
        manifest: dict[str, object],
        workspace_root: Path,
    ) -> tuple[str, ...]:
        if "__decode_error__" in manifest:
            return ("manifest.json is not valid JSON",)
        if "__shape_error__" in manifest:
            return ("manifest.json must contain an object payload",)

        problems: list[str] = []
        if manifest.get("snapshot_id") != snapshot.snapshot_id:
            problems.append("manifest snapshot_id does not match requested snapshot")
        if manifest.get("runtime_name") != snapshot.runtime_name:
            problems.append("manifest runtime_name does not match requested runtime")
        source_handle_id = manifest.get("source_handle_id")
        if not isinstance(source_handle_id, str) or not source_handle_id.strip():
            problems.append("manifest source_handle_id is missing")
        created_at = manifest.get("created_at")
        if not isinstance(created_at, str):
            problems.append("manifest created_at is missing")
        else:
            try:
                datetime.fromisoformat(created_at)
            except ValueError:
                problems.append("manifest created_at is invalid")
        manifest_workspace_root = manifest.get("workspace_root")
        if (
            not isinstance(manifest_workspace_root, str)
            or not manifest_workspace_root.strip()
        ):
            problems.append("manifest workspace_root is missing")
        elif (
            snapshot.workspace_root
            and manifest_workspace_root != snapshot.workspace_root
        ):
            problems.append("manifest workspace_root does not match snapshot metadata")
        if manifest.get("authority_digest") != snapshot.authority_digest:
            problems.append("manifest authority_digest does not match snapshot metadata")
        if manifest.get("image") != snapshot.image:
            problems.append("manifest image does not match snapshot metadata")
        try:
            workspace_digest = _workspace_digest(workspace_root)
        except RuntimeCapabilityError as exc:
            problems.append(str(exc))
        else:
            if manifest.get("workspace_digest") != workspace_digest:
                problems.append("snapshot workspace payload digest does not match manifest")
        return tuple(problems)

    def _forget_snapshot_path(self, snapshot_root: Path) -> None:
        for paths in self._snapshots_by_handle.values():
            while snapshot_root in paths:
                paths.remove(snapshot_root)

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
            "authority_digest": snapshot.authority_digest,
            "image": snapshot.image,
            "workspace_digest": _workspace_digest(snapshot_root / "workspace"),
        }
        (snapshot_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _workspace_digest(workspace_root: Path) -> str:
    digest = sha256()
    for path in sorted(workspace_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(workspace_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_dir():
            digest.update(b"D")
        elif path.is_file():
            digest.update(b"F")
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise RuntimeCapabilityError(
                f"runtime snapshot contains unsupported file type: {relative.decode()}"
            )
    return digest.hexdigest()
