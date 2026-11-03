"""A logical Host workspace neither mounts nor writes until resource demand."""

from uuid import uuid4

import pytest
from agent_core.domain.workspace_control import WorkspaceId, WorkspaceSource, WorkspaceSourceKind
from agent_runtime.workspace_provisioner import PostgresWorkspaceProvisioner
from agent_runtime.workspace_runtime_resolver import (
    WorkspaceRuntimeResolutionError,
    WorkspaceRuntimeResolver,
)
from agent_storage.postgres.workspace_control import PostgresWorkspaceControlStore


@pytest.mark.parametrize("cancelled", [False, True])
def test_physical_workspace_is_prepared_only_after_current_owner_check(
    postgres_dsn, tmp_path, cancelled,
):
    store = PostgresWorkspaceControlStore(postgres_dsn, deployment_namespace=f"lazy-{uuid4()}")
    session_id, workspace_id = uuid4(), WorkspaceId(uuid4())
    store.create_pending(
        WorkspaceSource(kind=WorkspaceSourceKind.HOST_REFERENCE, locator="opaque"),
        workspace_id=workspace_id, quota_bytes=1024**2, owner_session_id=session_id,
        idempotency_key=str(uuid4()),
    )
    physical_calls = []
    def forbidden_artifact(*_):
        pytest.fail("Host workspace must not load repository/attachment bytes")

    provisioner = PostgresWorkspaceProvisioner(
        store, volume_root=tmp_path, artifact_reader=forbidden_artifact,
        snapshot_writer=forbidden_artifact, snapshot_reader=forbidden_artifact,
    )
    resolver = WorkspaceRuntimeResolver(
        provisioner,
        prepare_volume=lambda *args: physical_calls.append(("prepare", args)),
        verify_volume=lambda *args: physical_calls.append(("verify", args)),
    )
    ref = f"workspace://{workspace_id}"
    root = resolver.planned_host_root(ref, session_id=session_id)
    assert root == tmp_path / str(workspace_id)
    assert root is not None and not root.exists() and not physical_calls
    with pytest.raises(WorkspaceRuntimeResolutionError, match="different Session"):
        resolver.resolve(ref, session_id=uuid4(), expected_host_root=root, check=lambda: None)
    assert not physical_calls

    def check():
        if cancelled and physical_calls:
            raise InterruptedError("stopped")
    if cancelled:
        with pytest.raises(InterruptedError, match="stopped"):
            resolver.resolve(ref, session_id=session_id, expected_host_root=root, check=check)
        assert not root.exists() and [call[0] for call in physical_calls] == ["prepare"]
    else:
        assert resolver.resolve(
            ref, session_id=session_id, expected_host_root=root, check=check,
        ) == root
        assert (root / ".zebra-host-reference").read_text() == "opaque\n"
        assert [call[0] for call in physical_calls] == ["prepare", "verify"]
