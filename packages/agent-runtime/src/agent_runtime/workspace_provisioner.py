"""Lease-disciplined workspace provisioner over the PostgreSQL authority."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from agent_core.domain.workspace_control import (
    WorkspaceAction,
    WorkspaceId,
    WorkspaceInstance,
    WorkspaceLifecycleState,
    WorkspaceSource,
    WorkspaceSourceKind,
)
from agent_core.ports.workspace_control import (
    WorkspaceOperationReceipt,
    WorkspaceProvisionCommand,
    WorkspaceProvisionerPort,
    WorkspaceSnapshotRef,
)
from agent_storage.postgres.workspace_control import PostgresWorkspaceControlStore

from agent_runtime.workspace_materialization import (
    WorkspaceMaterializationError,
    materialize_archive,
    materialize_git,
    materialize_snapshot_bytes,
    workspace_tree_digest,
)

BytesReader = Callable[[str], bytes]
BytesWriter = Callable[[bytes], str]


class WorkspaceProvisionerError(ValueError):
    """Provisioning input or durable-state mismatch."""


class PostgresWorkspaceProvisioner(WorkspaceProvisionerPort):
    """Materialize sources under CAS transitions; failures land in uncertain.

    ``artifact_reader`` serves uploaded-archive payloads, ``snapshot_reader``
    and ``snapshot_writer`` serve durable snapshot bytes; all are opaque to
    this orchestration and owned by composition roots.
    """

    def __init__(
        self,
        store: PostgresWorkspaceControlStore,
        *,
        volume_root: Path,
        artifact_reader: BytesReader,
        snapshot_writer: BytesWriter,
        snapshot_reader: BytesReader,
        namespace_quota_bytes: int | None = None,
        single_root_layout: bool = False,
    ) -> None:
        self._store = store
        self._volume_root = volume_root
        self._artifact_reader = artifact_reader
        self._snapshot_writer = snapshot_writer
        self._snapshot_reader = snapshot_reader
        self._namespace_quota_bytes = namespace_quota_bytes
        self._single_root_layout = single_root_layout

    @property
    def store(self) -> PostgresWorkspaceControlStore:
        return self._store

    def provision(self, command: WorkspaceProvisionCommand) -> WorkspaceInstance:
        if (
            self._namespace_quota_bytes is not None
            and self._store.get(command.workspace_id) is None
        ):
            live = self._store.namespace_live_quota_bytes()
            if live + command.quota_bytes > self._namespace_quota_bytes:
                raise WorkspaceProvisionerError(
                    "namespace workspace quota exceeded: "
                    f"{live} live + {command.quota_bytes} requested "
                    f"> {self._namespace_quota_bytes} budget"
                )
        if self._store.get(command.workspace_id) is None:
            self._store.create_pending(
                command.source,
                workspace_id=command.workspace_id,
                quota_bytes=command.quota_bytes,
                owner_session_id=command.owner_session_id,
                idempotency_key=command.idempotency_key,
            )
        return self.provision_existing(command.workspace_id)

    def provision_existing(self, workspace_id: WorkspaceId) -> WorkspaceInstance:
        """Provision from the instance's own durable source facts."""
        existing = self._store.get(workspace_id)
        if existing is None:
            raise WorkspaceProvisionerError("workspace instance is missing")
        if existing.state is not WorkspaceLifecycleState.PENDING:
            return existing
        self._store.transition(workspace_id, WorkspaceAction.PROVISION_START)
        target = self._volume_path(workspace_id)
        _reset_target(target)
        try:
            revision, digest = self._materialize(existing.source, target)
        except WorkspaceMaterializationError:
            self._store.transition(workspace_id, WorkspaceAction.PROVISION_MARK_UNCERTAIN)
            raise
        instance, _ = self._store.transition(
            workspace_id,
            WorkspaceAction.PROVISION_SUCCEED,
            materialized_revision=revision,
            content_digest=digest,
            volume_ref=str(target),
        )
        return instance

    def snapshot(self, workspace_id: WorkspaceId) -> WorkspaceSnapshotRef:
        instance = self._require_ready(workspace_id)
        root = Path(instance.volume_ref or "")
        digest = workspace_tree_digest(root)
        object_uri = self._snapshot_writer(_tar_directory(root))
        ref = WorkspaceSnapshotRef(
            snapshot_id=uuid4(),
            workspace_id=workspace_id,
            materialized_revision=instance.materialized_revision or "unknown",
            content_digest=digest,
            object_uri=object_uri,
        )
        self._store.transition(workspace_id, WorkspaceAction.SNAPSHOT)
        return self._store.record_snapshot(ref)

    def restore(
        self,
        snapshot: WorkspaceSnapshotRef,
        *,
        deployment_namespace: str,
        quota_bytes: int,
        idempotency_key: str,
    ) -> WorkspaceInstance:
        source = WorkspaceSource(
            kind=WorkspaceSourceKind.DURABLE_SNAPSHOT,
            locator=snapshot.object_uri,
            content_digest=snapshot.content_digest,
        )
        command = WorkspaceProvisionCommand(
            workspace_id=WorkspaceId(uuid4()),
            deployment_namespace=deployment_namespace,
            source=source,
            quota_bytes=quota_bytes,
            idempotency_key=idempotency_key,
        )
        instance, _ = self._store.create_pending(
            source,
            workspace_id=command.workspace_id,
            quota_bytes=quota_bytes,
            owner_session_id=None,
            idempotency_key=idempotency_key,
        )
        self._store.transition(command.workspace_id, WorkspaceAction.PROVISION_START)
        target = self._volume_path(command.workspace_id)
        shutil.rmtree(target, ignore_errors=True)
        try:
            payload = self._snapshot_reader(snapshot.object_uri)
            digest = materialize_snapshot_bytes(payload, target=target)
            if digest != snapshot.content_digest:
                raise WorkspaceMaterializationError(
                    "digest_mismatch", "restored tree differs from the durable snapshot"
                )
        except WorkspaceMaterializationError:
            self._store.transition(command.workspace_id, WorkspaceAction.PROVISION_MARK_UNCERTAIN)
            raise
        restored, _ = self._store.transition(
            command.workspace_id,
            WorkspaceAction.PROVISION_SUCCEED,
            materialized_revision=snapshot.materialized_revision,
            content_digest=digest,
            volume_ref=str(target),
        )
        return restored

    def expire_stale_provisioning(self, *, older_than_seconds: int) -> tuple[WorkspaceId, ...]:
        """Delegate the crash-orphan sweep; reconcile_uncertain resolves them."""
        return self._store.expire_stale_provisioning(older_than_seconds=older_than_seconds)

    def release(self, workspace_id: WorkspaceId) -> WorkspaceOperationReceipt:
        instance = self._store.get(workspace_id)
        if instance is None:
            raise WorkspaceProvisionerError("workspace instance is missing")
        if instance.volume_ref:
            shutil.rmtree(instance.volume_ref, ignore_errors=True)
        _, receipt = self._store.transition(workspace_id, WorkspaceAction.RELEASE)
        return receipt

    def reconcile_uncertain(
        self, *, deployment_namespace: str, limit: int = 100
    ) -> tuple[WorkspaceOperationReceipt, ...]:
        receipts: list[WorkspaceOperationReceipt] = []
        for instance in self._store.list_uncertain(limit=limit):
            target = self._volume_path(instance.workspace_id)
            shutil.rmtree(target, ignore_errors=True)
            try:
                revision, digest = self._materialize(instance.source, target)
                _, receipt = self._store.transition(
                    instance.workspace_id,
                    WorkspaceAction.UNCERTAIN_RESOLVE_SUCCEED,
                    materialized_revision=revision,
                    content_digest=digest,
                    volume_ref=str(target),
                )
            except WorkspaceMaterializationError:
                _, receipt = self._store.transition(
                    instance.workspace_id,
                    WorkspaceAction.UNCERTAIN_RESOLVE_FAIL,
                )
            receipts.append(receipt)
        return tuple(receipts)

    def _materialize(self, source: WorkspaceSource, target: Path) -> tuple[str, str]:
        if source.kind is WorkspaceSourceKind.GIT_REPOSITORY:
            return materialize_git(source, target)
        if source.kind is WorkspaceSourceKind.UPLOADED_ARCHIVE:
            return materialize_archive(
                source,
                target,
                read_archive=lambda uri: self._artifact_reader(uri),
            )
        if source.kind is WorkspaceSourceKind.DURABLE_SNAPSHOT:
            payload = self._snapshot_reader(source.locator)
            digest = materialize_snapshot_bytes(payload, target=target)
            if source.content_digest is not None and digest != source.content_digest:
                raise WorkspaceMaterializationError(
                    "digest_mismatch", "materialized tree differs from the source digest"
                )
            return source.locator, digest
        raise WorkspaceMaterializationError(
            "unsupported_source_kind", f"materialization is not defined for {source.kind}"
        )

    def _require_ready(self, workspace_id: WorkspaceId) -> WorkspaceInstance:
        instance = self._store.get(workspace_id)
        if instance is None:
            raise WorkspaceProvisionerError("workspace instance is missing")
        if (
            instance.state
            not in {
                WorkspaceLifecycleState.READY,
                WorkspaceLifecycleState.SEALED,
            }
            or not instance.volume_ref
        ):
            raise WorkspaceProvisionerError(
                "snapshots require a ready workspace with a materialized volume"
            )
        return instance

    def _volume_path(self, workspace_id: WorkspaceId) -> Path:
        if self._single_root_layout:
            return self._volume_root
        return self._volume_root / str(workspace_id)


def _reset_target(target: Path) -> None:
    """Mount points keep their mount; plain directories are replaced."""
    import os

    if os.path.ismount(target):
        for child in target.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        return
    shutil.rmtree(target, ignore_errors=True)


def _tar_directory(root: Path) -> bytes:
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(root.rglob("*")):
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    return buffer.getvalue()
