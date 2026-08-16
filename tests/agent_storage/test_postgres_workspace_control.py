"""Real PostgreSQL coverage for the Workspace Control Plane authority (v18)."""

from __future__ import annotations

import os
from collections.abc import Generator
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.workspace_control import (
    WorkspaceAction,
    WorkspaceId,
    WorkspaceLifecycleState,
    WorkspaceSource,
    WorkspaceSourceKind,
    WorkspaceTransitionError,
)
from agent_core.ports.workspace_control import WorkspaceSnapshotRef
from agent_storage import PostgresWorkspaceControlStore, apply_postgres_migrations
from psycopg import sql
from psycopg.conninfo import make_conninfo

DIGEST = "b" * 64


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"workspace_control_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _git_source() -> WorkspaceSource:
    return WorkspaceSource(
        kind=WorkspaceSourceKind.GIT_REPOSITORY,
        locator="https://git.example/zebra/repo",
        pinned_revision="rev-1",
    )


def _store(dsn: str, namespace: str = "cloud-a") -> PostgresWorkspaceControlStore:
    return PostgresWorkspaceControlStore(dsn, deployment_namespace=namespace)


def test_provision_is_idempotent_per_key(dsn: str) -> None:
    store = _store(dsn)
    workspace_id = WorkspaceId(uuid4())
    first, first_receipt = store.create_pending(
        _git_source(),
        workspace_id=workspace_id,
        quota_bytes=1024 * 1024,
        owner_session_id=None,
        idempotency_key="provision-1",
    )
    second, second_receipt = store.create_pending(
        _git_source(),
        workspace_id=WorkspaceId(uuid4()),
        quota_bytes=2048,
        owner_session_id=None,
        idempotency_key="provision-1",
    )
    assert first.state is WorkspaceLifecycleState.PENDING
    assert second.workspace_id == first.workspace_id
    assert not first_receipt.idempotent_replay
    assert second_receipt.idempotent_replay


def test_lifecycle_transitions_are_cas_and_domain_checked(dsn: str) -> None:
    store = _store(dsn)
    workspace_id = WorkspaceId(uuid4())
    store.create_pending(
        _git_source(),
        workspace_id=workspace_id,
        quota_bytes=1024 * 1024,
        owner_session_id=None,
        idempotency_key=f"provision-{workspace_id}",
    )
    instance, _ = store.transition(workspace_id, WorkspaceAction.PROVISION_START)
    assert instance.state is WorkspaceLifecycleState.PROVISIONING
    with pytest.raises(WorkspaceTransitionError):
        store.transition(workspace_id, WorkspaceAction.SEAL)
    instance, _ = store.transition(
        workspace_id,
        WorkspaceAction.PROVISION_SUCCEED,
        materialized_revision="rev-1",
        content_digest=DIGEST,
        volume_ref="volume://pool/ws-1",
    )
    assert instance.state is WorkspaceLifecycleState.READY
    assert instance.content_digest == DIGEST
    instance, _ = store.transition(workspace_id, WorkspaceAction.SEAL)
    assert instance.state is WorkspaceLifecycleState.SEALED
    instance, _ = store.transition(workspace_id, WorkspaceAction.RELEASE)
    assert instance.state is WorkspaceLifecycleState.RELEASED


def test_uncertain_listing_and_resolution(dsn: str) -> None:
    store = _store(dsn)
    workspace_id = WorkspaceId(uuid4())
    store.create_pending(
        _git_source(),
        workspace_id=workspace_id,
        quota_bytes=1024 * 1024,
        owner_session_id=None,
        idempotency_key=f"provision-{workspace_id}",
    )
    store.transition(workspace_id, WorkspaceAction.PROVISION_START)
    store.transition(workspace_id, WorkspaceAction.PROVISION_MARK_UNCERTAIN)
    listed = store.list_uncertain()
    assert any(entry.workspace_id == workspace_id for entry in listed)
    instance, _ = store.transition(
        workspace_id,
        WorkspaceAction.UNCERTAIN_RESOLVE_SUCCEED,
        materialized_revision="rev-1",
        content_digest=DIGEST,
    )
    assert instance.state is WorkspaceLifecycleState.READY
    assert store.list_uncertain() == ()


def test_namespace_isolation(dsn: str) -> None:
    first = _store(dsn, namespace="cloud-a")
    second = _store(dsn, namespace="cloud-b")
    workspace_id = WorkspaceId(uuid4())
    first.create_pending(
        _git_source(),
        workspace_id=workspace_id,
        quota_bytes=1024 * 1024,
        owner_session_id=None,
        idempotency_key=f"provision-{workspace_id}",
    )
    assert first.get(workspace_id) is not None
    assert second.get(workspace_id) is None


def test_snapshots_are_namespace_scoped_dsn_facts(dsn: str) -> None:
    store = _store(dsn)
    workspace_id = WorkspaceId(uuid4())
    store.create_pending(
        _git_source(),
        workspace_id=workspace_id,
        quota_bytes=1024 * 1024,
        owner_session_id=None,
        idempotency_key=f"provision-{workspace_id}",
    )
    store.transition(workspace_id, WorkspaceAction.PROVISION_START)
    store.transition(
        workspace_id,
        WorkspaceAction.PROVISION_SUCCEED,
        materialized_revision="rev-1",
        content_digest=DIGEST,
    )
    snapshot = WorkspaceSnapshotRef(
        snapshot_id=uuid4(),
        workspace_id=workspace_id,
        materialized_revision="rev-1",
        content_digest=DIGEST,
        object_uri="artifact://zebra/workspace-snapshots/repo/rev-1",
    )
    recorded = store.record_snapshot(snapshot)
    assert recorded == snapshot
    assert store.list_snapshots(workspace_id) == (snapshot,)
