"""Real-PostgreSQL delegation store tests (v26, SUBAGENT-DELEGATION-PG-01)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagent_delegation import (
    SubagentDelegationRequest,
    derive_child_binding,
)
from agent_core.domain.subagents import SubagentRole
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.subagent_delegation import (
    PostgresSubagentDelegationStore,
)
from psycopg import connect

PARENT_CAPS = capability_set(["agent.execute", "evidence.read"])


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"delegation-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _parent_binding(parent_task: TaskId) -> TaskBindingSnapshot:
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/parent@1",
        capabilities=PARENT_CAPS,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-a",
        authority_issuer="https://host-a.example.com",
        namespace_id="tenant-a",
        grant_digest="c" * 64,
        connector_id="host-a-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=PARENT_CAPS,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(parent_task),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=PARENT_CAPS,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def _child_admission(parent_binding: TaskBindingSnapshot, request: SubagentDelegationRequest):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Child task",
            user_input="collect evidence",
            workspace_root="/tmp/delegation-child",
        )
    )
    child_binding = derive_child_binding(
        parent_binding,
        request,
        child_task_id=bootstrap.session.session_id,
        child_definition_ceiling=capability_set(["evidence.read"]),
        zebra_child_policy_capabilities=capability_set(["evidence.read"]),
    )
    return TaskAdmissionRequest(
        events=tuple(bootstrap.events),
        session=bootstrap.session,
        workspace=rebuild_workspace(list(bootstrap.events)),
        binding=child_binding,
    )


def test_delegate_materializes_child_and_link(namespace: str, postgres_dsn: str) -> None:
    store = PostgresSubagentDelegationStore(postgres_dsn, deployment_namespace=namespace)
    parent = TaskId(uuid4())
    parent_binding = _parent_binding(parent)
    request = SubagentDelegationRequest(
        parent_task_id=parent,
        parent_attempt_number=1,
        parent_tool_call_id="call-1",
        delegation_index=0,
        role=SubagentRole.RESEARCHER,
        objective="Collect evidence",
        requested_capabilities=frozenset(capability_set(["evidence.read"])),
        child_definition_snapshot_digest="1" * 64,
        child_capability_profile_ref="profile/researcher@1",
        expected_parent_binding_digest=parent_binding.binding_digest,
    )
    receipt = store.delegate(request, _child_admission(parent_binding, request))
    assert receipt.status == "materialized"
    link = store.get_link(receipt.child_task_id)
    assert link is not None
    assert link.parent_task_id == parent
    assert link.parent_binding_digest == parent_binding.binding_digest


def test_replay_returns_the_same_child(namespace: str, postgres_dsn: str) -> None:
    store = PostgresSubagentDelegationStore(postgres_dsn, deployment_namespace=namespace)
    parent = TaskId(uuid4())
    parent_binding = _parent_binding(parent)
    request = SubagentDelegationRequest(
        parent_task_id=parent,
        parent_attempt_number=1,
        parent_tool_call_id="call-replay",
        delegation_index=0,
        role=SubagentRole.RESEARCHER,
        objective="Collect evidence again",
        requested_capabilities=frozenset(capability_set(["evidence.read"])),
        child_definition_snapshot_digest="1" * 64,
        child_capability_profile_ref="profile/researcher@1",
        expected_parent_binding_digest=parent_binding.binding_digest,
    )
    first = store.delegate(request, _child_admission(parent_binding, request))
    second = store.delegate(request, _child_admission(parent_binding, request))
    assert first.status == "materialized"
    assert second.status == "replayed"
    assert second.child_task_id == first.child_task_id


def test_migration_v26_table_exists(postgres_dsn: str, namespace: str) -> None:
    with connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_name = 'subagent_delegation_links'
            """
        ).fetchone()
    assert int(row[0]) == 1
