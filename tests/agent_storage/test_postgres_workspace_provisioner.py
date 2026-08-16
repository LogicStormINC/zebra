"""Real PostgreSQL coverage for the workspace provisioner orchestration."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Generator
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.workspace_control import (
    WorkspaceId,
    WorkspaceLifecycleState,
    WorkspaceSource,
    WorkspaceSourceKind,
)
from agent_core.ports.workspace_control import WorkspaceProvisionCommand
from agent_runtime.workspace_materialization import WorkspaceMaterializationError
from agent_runtime.workspace_provisioner import PostgresWorkspaceProvisioner
from agent_storage import PostgresWorkspaceControlStore, apply_postgres_migrations
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"workspace_provisioner_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(("git", "-C", str(repo), "init", "--quiet"), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(repo), "config", "user.email", "prov@example"),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "-C", str(repo), "config", "user.name", "Prov"),
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# provisioned\n")
    subprocess.run(("git", "-C", str(repo), "add", "."), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(repo), "commit", "--quiet", "-m", "initial"),
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ("git", "-C", str(repo), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return str(repo), revision


class _ObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def write(self, payload: bytes) -> str:
        uri = f"artifact://zebra/workspace/{sha256(payload).hexdigest()}"
        self.objects[uri] = payload
        return uri

    def read(self, uri: str) -> bytes:
        return self.objects[uri]


def _provisioner(dsn: str, tmp_path: Path) -> tuple[PostgresWorkspaceProvisioner, _ObjectStore]:
    store = PostgresWorkspaceControlStore(dsn, deployment_namespace="cloud-a")
    objects = _ObjectStore()
    return (
        PostgresWorkspaceProvisioner(
            store,
            volume_root=tmp_path / "volumes",
            artifact_reader=objects.read,
            snapshot_writer=objects.write,
            snapshot_reader=objects.read,
        ),
        objects,
    )


def test_provision_materializes_and_is_idempotent(
    dsn: str, git_repo: tuple[str, str], tmp_path: Path
) -> None:
    provisioner, _ = _provisioner(dsn, tmp_path)
    locator, revision = git_repo
    workspace_id = WorkspaceId(uuid4())
    command = WorkspaceProvisionCommand(
        workspace_id=workspace_id,
        deployment_namespace="cloud-a",
        source=WorkspaceSource(
            kind=WorkspaceSourceKind.GIT_REPOSITORY,
            locator=locator,
            pinned_revision=revision,
        ),
        quota_bytes=1024 * 1024,
        idempotency_key=f"provision-{workspace_id}",
    )
    instance = provisioner.provision(command)
    assert instance.state is WorkspaceLifecycleState.READY
    assert instance.materialized_revision == revision
    assert Path(instance.volume_ref or "").joinpath("README.md").is_file()
    replayed = provisioner.provision(command)
    assert replayed == instance


def test_failed_provision_lands_in_uncertain_and_reconciles(
    dsn: str, git_repo: tuple[str, str], tmp_path: Path
) -> None:
    provisioner, _ = _provisioner(dsn, tmp_path)
    locator, _ = git_repo
    workspace_id = WorkspaceId(uuid4())
    command = WorkspaceProvisionCommand(
        workspace_id=workspace_id,
        deployment_namespace="cloud-a",
        source=WorkspaceSource(
            kind=WorkspaceSourceKind.GIT_REPOSITORY,
            locator=locator,
            pinned_revision="9" * 40,
        ),
        quota_bytes=1024 * 1024,
        idempotency_key=f"provision-{workspace_id}",
    )
    with pytest.raises(WorkspaceMaterializationError, match="checkout_missing"):
        provisioner.provision(command)
    store = PostgresWorkspaceControlStore(dsn, deployment_namespace="cloud-a")
    assert store.get(workspace_id).state is WorkspaceLifecycleState.UNCERTAIN
    receipts = provisioner.reconcile_uncertain(deployment_namespace="cloud-a")
    assert receipts
    resolved = store.get(workspace_id)
    assert resolved.state is WorkspaceLifecycleState.FAILED
    assert store.list_uncertain() == ()


def test_snapshot_restore_and_release_roundtrip(
    dsn: str, git_repo: tuple[str, str], tmp_path: Path
) -> None:
    provisioner, _ = _provisioner(dsn, tmp_path)
    locator, revision = git_repo
    workspace_id = WorkspaceId(uuid4())
    instance = provisioner.provision(
        WorkspaceProvisionCommand(
            workspace_id=workspace_id,
            deployment_namespace="cloud-a",
            source=WorkspaceSource(
                kind=WorkspaceSourceKind.GIT_REPOSITORY,
                locator=locator,
                pinned_revision=revision,
            ),
            quota_bytes=1024 * 1024,
            idempotency_key=f"provision-{workspace_id}",
        )
    )
    snapshot = provisioner.snapshot(workspace_id)
    assert snapshot.materialized_revision == revision
    restored = provisioner.restore(
        snapshot,
        deployment_namespace="cloud-a",
        quota_bytes=1024 * 1024,
        idempotency_key=f"restore-{snapshot.snapshot_id}",
    )
    assert restored.state is WorkspaceLifecycleState.READY
    assert restored.content_digest == instance.content_digest
    assert Path(restored.volume_ref or "").joinpath("README.md").is_file()
    receipt = provisioner.release(workspace_id)
    assert receipt.resulting_state is WorkspaceLifecycleState.RELEASED
    assert not Path(instance.volume_ref or "").exists()
