"""Full-chain E2E: admission → delegation → child completion → wakeup event.

Starts a real PostgreSQL, exercises the actual store implementations,
and verifies that the parent's Event Stream receives the
SESSION_COMMAND_ACCEPTED wakeup after the child reaches terminal status.
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
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.subagent_delegation import (
    PostgresSubagentDelegationStore,
)
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
)
from psycopg import connect
from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService

CAPS = capability_set(["agent.execute", "evidence.read"])


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"fullchain-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _binding(task_id: TaskId) -> TaskBindingSnapshot:
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/parent@1",
        capabilities=CAPS,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-fc",
        authority_issuer="https://host-fc.example.com",
        namespace_id="tenant-fc",
        grant_digest="c" * 64,
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connector_id="host-fc-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=CAPS,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(task_id),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=CAPS,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def test_full_chain_admission_delegate_complete_wakeup(
    namespace: str, postgres_dsn: str
) -> None:
    admission = PostgresTaskAdmissionTransaction(
        postgres_dsn, deployment_namespace=namespace
    )

    # ── Step 1: Atomic admission with idempotency receipt ──
    parent_bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Full-chain parent",
            user_input="delegate research",
            workspace_root="/tmp/fc-parent",
        )
    )
    parent_id = TaskId(parent_bootstrap.session.session_id)
    parent_binding = _binding(parent_id)
    idem_key = f"e2e-{uuid4()}"
    idem = IdempotencyRecord(
        action="session.create",
        idempotency_key=idem_key,
        request_hash="r" * 64,
        status_code=201,
        response_body={"session_id": str(parent_id)},
        created_at=datetime.now(UTC),
    )
    receipt = admission.admit(
        TaskAdmissionRequest(
            events=tuple(parent_bootstrap.events),
            session=parent_bootstrap.session,
            workspace=rebuild_workspace(list(parent_bootstrap.events)),
            binding=parent_binding,
            idempotency=idem,
        )
    )
    assert receipt.event_count > 0
    assert receipt.binding_digest == parent_binding.binding_digest

    # ── Step 2: Idempotent replay returns the SAME session (no duplicate) ──
    replay = admission.admit(
        TaskAdmissionRequest(
            events=tuple(parent_bootstrap.events),
            session=parent_bootstrap.session,
            workspace=rebuild_workspace(list(parent_bootstrap.events)),
            binding=parent_binding,
            idempotency=idem,
        )
    )
    assert replay.idempotent_replay is True
    assert replay.event_count == 0

    # ── Step 3: Durable delegation materializes the child Task ──
    delegation = PostgresSubagentDelegationStore(
        postgres_dsn, deployment_namespace=namespace
    )
    child_bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Full-chain child",
            user_input="gather evidence",
            workspace_root="/tmp/fc-child",
        )
    )
    child_id = TaskId(child_bootstrap.session.session_id)
    request = SubagentDelegationRequest(
        parent_task_id=parent_id,
        parent_attempt_number=1,
        parent_tool_call_id="call-fc",
        delegation_index=0,
        role=SubagentRole.RESEARCHER,
        objective="Gather evidence",
        requested_capabilities=frozenset(capability_set(["evidence.read"])),
        child_definition_snapshot_digest="1" * 64,
        child_capability_profile_ref="profile/researcher@1",
        expected_parent_binding_digest=parent_binding.binding_digest,
    )
    # derive the child binding properly
    from agent_core.domain.subagent_delegation import derive_child_binding

    derived = derive_child_binding(
        parent_binding,
        request,
        child_task_id=child_id,
        child_definition_ceiling=capability_set(["evidence.read"]),
        zebra_child_policy_capabilities=capability_set(["evidence.read"]),
    )
    child_receipt = delegation.delegate(
        request,
        TaskAdmissionRequest(
            events=tuple(child_bootstrap.events),
            session=child_bootstrap.session,
            workspace=rebuild_workspace(list(child_bootstrap.events)),
            binding=derived,
        ),
    )
    assert child_receipt.status == "materialized"

    # ── Step 4: Child reaches terminal status (simulate Worker completion) ──
    with connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE session_projections
            SET status = 'completed', updated_at = NOW()
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (namespace, str(child_id)),
        )

    # ── Step 5: Wakeup service detects the terminal child and writes the event ──
    wakeup = ChildCompletionWakeupService(
        postgres_dsn, deployment_namespace=namespace
    )
    terminals = wakeup.poll_terminal_children()
    assert len(terminals) == 1
    assert terminals[0]["status"] is ChildTerminalStatus.COMPLETED

    result = wakeup.process_child_terminal(
        child_id, status=ChildTerminalStatus.COMPLETED, result_bundle_digest="9" * 64
    )
    assert result is not None
    assert result["decision"] == "resume"
    assert result["any_success"] is True

    # ── Step 6: Verify the parent's Event Stream got the SESSION_COMMAND_ACCEPTED ──
    with connect(postgres_dsn) as connection:
        events = connection.execute(
            """
            SELECT event_type FROM session_events
            WHERE deployment_namespace = %s AND session_id = %s
            ORDER BY sequence
            """,
            (namespace, str(parent_id)),
        ).fetchall()
    event_types = [row[0] for row in events]
    assert "session_command_accepted" in event_types

    # ── Step 7: Re-poll — the link is terminal, no more wakeups fire ──
    terminals_after = wakeup.poll_terminal_children()
    assert len(terminals_after) == 0

    # ── Step 8: Table verification ──
    with connect(postgres_dsn) as connection:
        links = connection.execute(
            "SELECT count(*) FROM subagent_delegation_links WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchone()
        bindings = connection.execute(
            "SELECT count(*) FROM task_binding_snapshots WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchone()
        idem_count = connection.execute(
            """SELECT count(*) FROM control_plane_idempotency_records
            WHERE deployment_namespace = %s AND idempotency_key = %s""",
            (namespace, idem_key),
        ).fetchone()
    assert int(links[0]) == 1
    assert int(bindings[0]) >= 2  # parent + child
    assert int(idem_count[0]) == 1
