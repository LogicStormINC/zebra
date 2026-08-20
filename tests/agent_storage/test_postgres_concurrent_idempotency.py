"""Concurrent idempotency over real PostgreSQL (2026-08-20 audit P1s).

Two races the serial tests cannot see:
- N concurrent admissions sharing one idempotency key must produce ONE
  session and N identical replays (no UniqueViolation, no second Task);
- N concurrent delegations sharing one frozen key must produce ONE child
  and N-1 replay receipts of the winner (no DelegationReplayError).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
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
from agent_core.domain.subagent_delegation import SubagentDelegationRequest
from agent_core.domain.subagents import SubagentRole
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.postgres.subagent_delegation import (
    PostgresSubagentDelegationStore,
)
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
)
from psycopg import connect

CAPS = capability_set(["agent.execute", "evidence.read"])
WORKERS = 16


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"conc-{uuid4()}"
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
        host_app_id="host-conc",
        authority_issuer="https://host-conc.example.com",
        namespace_id="tenant-conc",
        grant_digest="c" * 64,
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connector_id="host-conc-main",
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


def _admission(idempotency: IdempotencyRecord | None):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="concurrent",
            user_input="concurrent idempotency probe",
            workspace_root="/tmp/concurrent-probe",
            policy_profile="read_only",
            network_profile="none",
        )
    )
    return TaskAdmissionRequest(
        events=tuple(bootstrap.events),
        session=bootstrap.session,
        workspace=rebuild_workspace(list(bootstrap.events)),
        binding=_binding(TaskId(bootstrap.session.session_id)),
        idempotency=idempotency,
    )


def test_concurrent_admissions_share_one_idempotent_session(
    postgres_dsn: str, namespace: str
) -> None:
    key = f"conc-adm-{uuid4()}"
    receipt = IdempotencyRecord(
        action="session.create",
        idempotency_key=key,
        request_hash="1" * 64,
        status_code=201,
        response_body={"session_id": str(uuid4())},
        created_at=datetime.now(UTC),
    )
    def admit(_: int):
        transaction = PostgresTaskAdmissionTransaction(
            postgres_dsn, deployment_namespace=namespace
        )
        return transaction.admit(_admission(receipt))

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        receipts = list(executor.map(admit, range(WORKERS)))

    created = [r for r in receipts if not r.idempotent_replay]
    replayed = [r for r in receipts if r.idempotent_replay]
    assert len(created) == 1, "exactly one admission may create the Task"
    assert len(replayed) == WORKERS - 1
    for r in replayed:
        assert r.replayed_record is not None
        assert r.replayed_record.request_hash == "1" * 64
        assert r.replayed_record.response_body == receipt.response_body
    with connect(postgres_dsn) as connection:
        rows = connection.execute(
            """
            SELECT count(*) FROM session_streams
            WHERE deployment_namespace = %s
            """,
            (namespace,),
        ).fetchone()
    assert rows[0] == 1, "no duplicate sessions may survive the race"


def test_concurrent_delegations_replay_the_winner(
    postgres_dsn: str, namespace: str
) -> None:
    parent = TaskId(uuid4())
    parent_binding = _binding(parent)
    request = SubagentDelegationRequest(
        parent_task_id=parent,
        parent_attempt_number=1,
        parent_tool_call_id="call-conc-1",
        delegation_index=0,
        role=SubagentRole.RESEARCHER,
        objective="concurrent delegation probe",
        requested_capabilities=CAPS,
        child_definition_snapshot_digest="0" * 64,
        child_capability_profile_ref="profile/researcher@1",
        expected_parent_binding_digest=parent_binding.binding_digest,
    )

    def delegate(_: int):
        store = PostgresSubagentDelegationStore(
            postgres_dsn, deployment_namespace=namespace
        )
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="Research: concurrent delegation probe",
                user_input="concurrent delegation probe",
                workspace_root="/tmp/concurrent-probe",
                policy_profile="read_only",
                network_profile="none",
            )
        )
        from agent_core.domain.subagent_delegation import derive_child_binding

        child_binding = derive_child_binding(
            parent_binding,
            request,
            child_task_id=TaskId(bootstrap.session.session_id),
            child_definition_ceiling=CAPS,
            zebra_child_policy_capabilities=CAPS,
        )
        return store.delegate(
            request,
            TaskAdmissionRequest(
                events=tuple(bootstrap.events),
                session=bootstrap.session,
                workspace=rebuild_workspace(list(bootstrap.events)),
                binding=child_binding,
            ),
        )

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        receipts = list(executor.map(delegate, range(WORKERS)))

    materialized = [r for r in receipts if r.status == "materialized"]
    replayed = [r for r in receipts if r.status == "replayed"]
    assert len(materialized) == 1, "exactly one delegation may materialize a child"
    assert len(replayed) == WORKERS - 1, "losers must replay the winner, not error"
    winner_child = materialized[0].child_task_id
    for r in replayed:
        assert r.child_task_id == winner_child
        assert r.child_binding_digest == materialized[0].child_binding_digest
    with connect(postgres_dsn) as connection:
        links = connection.execute(
            """
            SELECT count(*) FROM subagent_delegation_links
            WHERE deployment_namespace = %s AND parent_task_id = %s
            """,
            (namespace, str(parent)),
        ).fetchone()
        children = connection.execute(
            """
            SELECT count(*) FROM session_streams
            WHERE deployment_namespace = %s
            """,
            (namespace,),
        ).fetchone()
    assert links[0] == 1, "exactly one delegation link may survive"
    assert children[0] == 1, "loser children must roll back with their transactions"
