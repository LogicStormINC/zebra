"""CLOUD-WORKSPACE-CP-CON-01 contract coverage."""

from uuid import uuid4

import pytest
from agent_core.domain.workspace_control import (
    WorkspaceAction,
    WorkspaceInstance,
    WorkspaceLifecycleState,
    WorkspaceSource,
    WorkspaceSourceKind,
    WorkspaceTransitionError,
    next_workspace_state,
    workspace_actions_for,
)
from agent_core.ports.workspace_control import (
    WorkspaceProvisionCommand,
    WorkspaceSnapshotRef,
)
from pydantic import ValidationError

DIGEST = "a" * 64


def _git_source() -> WorkspaceSource:
    return WorkspaceSource(
        kind=WorkspaceSourceKind.GIT_REPOSITORY,
        locator="https://git.example/zebra/repo",
        pinned_revision="abc123",
    )


def _instance(state: WorkspaceLifecycleState, **overrides) -> WorkspaceInstance:
    payload = {
        "workspace_id": uuid4(),
        "deployment_namespace": "cloud-a",
        "source": _git_source(),
        "state": state,
        "quota_bytes": 1024 * 1024,
    }
    if state in {WorkspaceLifecycleState.READY, WorkspaceLifecycleState.SEALED}:
        payload.update({"materialized_revision": "abc123", "content_digest": DIGEST})
    payload.update(overrides)
    return WorkspaceInstance(**payload)


def test_git_sources_must_pin_a_revision() -> None:
    with pytest.raises(ValidationError, match="must pin a revision"):
        WorkspaceSource(
            kind=WorkspaceSourceKind.GIT_REPOSITORY,
            locator="https://git.example/repo",
        )


def test_archive_sources_must_reference_their_artifact() -> None:
    with pytest.raises(ValidationError, match="artifact uri"):
        WorkspaceSource(
            kind=WorkspaceSourceKind.UPLOADED_ARCHIVE,
            locator="upload://zebra/repo.tar",
        )


def test_pinning_is_reserved_for_git_sources() -> None:
    with pytest.raises(ValidationError, match="only valid for git repository"):
        WorkspaceSource(
            kind=WorkspaceSourceKind.DURABLE_SNAPSHOT,
            locator="artifact://zebra/snapshots/repo",
            pinned_revision="abc123",
        )


def test_digest_must_be_sha256_hex() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        WorkspaceSource(
            kind=WorkspaceSourceKind.DURABLE_SNAPSHOT,
            locator="artifact://zebra/snapshots/repo",
            content_digest="not-a-digest",
        )


def test_ready_instances_require_revision_and_digest() -> None:
    with pytest.raises(ValidationError, match="revision and content digest"):
        _instance(WorkspaceLifecycleState.READY, materialized_revision=None)


def test_lifecycle_table_happy_path() -> None:
    state = WorkspaceLifecycleState.PENDING
    state = next_workspace_state(state, WorkspaceAction.PROVISION_START)
    assert state is WorkspaceLifecycleState.PROVISIONING
    state = next_workspace_state(state, WorkspaceAction.PROVISION_SUCCEED)
    assert state is WorkspaceLifecycleState.READY
    state = next_workspace_state(state, WorkspaceAction.SEAL)
    assert state is WorkspaceLifecycleState.SEALED
    state = next_workspace_state(state, WorkspaceAction.RELEASE)
    assert state is WorkspaceLifecycleState.RELEASED
    assert workspace_actions_for(state) == frozenset()


def test_uncertain_provisions_resolve_deterministically() -> None:
    uncertain = next_workspace_state(
        WorkspaceLifecycleState.PROVISIONING,
        WorkspaceAction.PROVISION_MARK_UNCERTAIN,
    )
    assert uncertain is WorkspaceLifecycleState.UNCERTAIN
    assert (
        next_workspace_state(uncertain, WorkspaceAction.UNCERTAIN_RESOLVE_SUCCEED)
        is WorkspaceLifecycleState.READY
    )
    assert (
        next_workspace_state(uncertain, WorkspaceAction.UNCERTAIN_RESOLVE_FAIL)
        is WorkspaceLifecycleState.FAILED
    )


def test_illegal_transitions_fail_closed() -> None:
    with pytest.raises(WorkspaceTransitionError, match="illegal"):
        next_workspace_state(WorkspaceLifecycleState.RELEASED, WorkspaceAction.PROVISION_START)
    with pytest.raises(WorkspaceTransitionError, match="illegal"):
        next_workspace_state(WorkspaceLifecycleState.PENDING, WorkspaceAction.PROVISION_SUCCEED)
    with pytest.raises(WorkspaceTransitionError, match="illegal"):
        next_workspace_state(
            WorkspaceLifecycleState.READY, WorkspaceAction.UNCERTAIN_RESOLVE_SUCCEED
        )


def test_snapshot_only_from_ready_or_sealed() -> None:
    assert WorkspaceAction.SNAPSHOT in workspace_actions_for(WorkspaceLifecycleState.READY)
    assert WorkspaceAction.SNAPSHOT in workspace_actions_for(WorkspaceLifecycleState.SEALED)
    with pytest.raises(WorkspaceTransitionError, match="illegal"):
        next_workspace_state(WorkspaceLifecycleState.PROVISIONING, WorkspaceAction.SNAPSHOT)


def test_provision_command_is_idempotent_shaped() -> None:
    command = WorkspaceProvisionCommand(
        workspace_id=uuid4(),
        deployment_namespace="cloud-a",
        source=_git_source(),
        quota_bytes=1024 * 1024,
        idempotency_key="provision-1",
    )
    assert command.owner_session_id is None
    with pytest.raises(ValidationError, match="non-blank"):
        WorkspaceProvisionCommand(
            workspace_id=uuid4(),
            deployment_namespace=" ",
            source=_git_source(),
            quota_bytes=1024 * 1024,
            idempotency_key="provision-1",
        )


def test_snapshot_refs_carry_durable_facts() -> None:
    ref = WorkspaceSnapshotRef(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        materialized_revision="abc123",
        content_digest=DIGEST,
        object_uri="artifact://zebra/snapshots/repo/abc123",
    )
    assert ref.content_digest == DIGEST
    with pytest.raises(ValidationError, match="sha256"):
        WorkspaceSnapshotRef(
            snapshot_id=uuid4(),
            workspace_id=uuid4(),
            materialized_revision="abc123",
            content_digest="z" * 64,
            object_uri="artifact://zebra/snapshots/repo/abc123",
        )
