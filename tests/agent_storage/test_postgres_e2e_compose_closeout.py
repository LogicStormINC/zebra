"""Real-PG E2E: admission → binding freeze → delegation → child terminal → wakeup.

Phase F5: the full composition-closeout chain against a disposable
PostgreSQL instance. Each step uses the real store implementations.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import ChildTerminalStatus
from agent_core.domain.subagent_delegation import SubagentDelegationRequest
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
from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"e2e-compose-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


CAPS = capability_set(["agent.execute", "evidence.read"])


def _parent_binding(parent_task: TaskId) -> TaskBindingSnapshot:
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/parent@1",
        capabilities=CAPS,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-e2e",
        authority_issuer="https://host-e2e.example.com",
        namespace_id="tenant-e2e",
        grant_digest="c" * 64,
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connector_id="host-e2e-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=CAPS,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(parent_task),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=CAPS,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def _delegation_request(parent: TaskId, parent_binding: TaskBindingSnapshot):
    return SubagentDelegationRequest(
        parent_task_id=parent,
        parent_attempt_number=1,
        parent_tool_call_id="call-e2e",
        delegation_index=0,
        role=SubagentRole.RESEARCHER,
        objective="Collect evidence for the E2E proof",
        requested_capabilities=frozenset(capability_set(["evidence.read"])),
        child_definition_snapshot_digest="1" * 64,
        child_capability_profile_ref="profile/researcher@1",
        expected_parent_binding_digest=parent_binding.binding_digest,
    )


def _child_admission(parent_binding: TaskBindingSnapshot, request):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="E2E child",
            user_input="collect evidence",
            workspace_root="/tmp/e2e-child",
        )
    )
    from agent_core.domain.subagent_delegation import derive_child_binding

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


def test_e2e_admission_freeze_delegate_complete_wakeup(
    namespace: str, postgres_dsn: str
) -> None:
    """The full F-chain: freeze → delegate → child terminal → wakeup."""

    # Step 1: Admission (F3) — atomically create the parent session + binding
    parent_bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="E2E parent",
            user_input="delegate research",
            workspace_root="/tmp/e2e-parent",
        )
    )
    parent_task = TaskId(parent_bootstrap.session.session_id)
    parent_binding = _parent_binding(parent_task)
    from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
    from agent_storage.postgres.task_admission import (
        PostgresTaskAdmissionTransaction,
    )

    PostgresTaskAdmissionTransaction(
        postgres_dsn, deployment_namespace=namespace
    ).admit(
        TaskAdmissionRequest(
            events=tuple(parent_bootstrap.events),
            session=parent_bootstrap.session,
            workspace=rebuild_workspace(list(parent_bootstrap.events)),
            binding=parent_binding,
        )
    )

    # Step 2: Delegation (Phase B) — materialize the child atomically
    delegation_store = PostgresSubagentDelegationStore(
        postgres_dsn, deployment_namespace=namespace
    )
    request = _delegation_request(parent_task, parent_binding)
    receipt = delegation_store.delegate(
        request, _child_admission(parent_binding, request)
    )
    assert receipt.status == "materialized"
    child_task = receipt.child_task_id

    # Step 3: Verify the link is durable
    link = delegation_store.get_link(child_task)
    assert link is not None
    assert link.parent_task_id == parent_task

    # Step 4: Child completes (F4) — process the terminal
    wakeup_service = ChildCompletionWakeupService(
        postgres_dsn, deployment_namespace=namespace
    )
    wakeup = wakeup_service.process_child_terminal(
        child_task,
        status=ChildTerminalStatus.COMPLETED,
        result_bundle_digest="9" * 64,
    )
    assert wakeup is not None
    assert wakeup["parent_task_id"] == str(parent_task)
    assert wakeup["decision"] == "resume"
    assert wakeup["any_success"] is True

    # Step 5: Replay the child terminal — idempotent (same wakeup, no duplicate child)
    replay = delegation_store.delegate(
        request, _child_admission(parent_binding, request)
    )
    assert replay.status == "replayed"
    assert replay.child_task_id == child_task

    # Step 6: The v25/v26 tables exist and hold the right rows
    with connect(postgres_dsn) as connection:
        bindings = connection.execute(
            "SELECT count(*) FROM task_binding_snapshots WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchone()
        links = connection.execute(
            "SELECT count(*) FROM subagent_delegation_links WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchone()
    assert int(bindings[0]) >= 2  # parent + child
    assert int(links[0]) == 1
