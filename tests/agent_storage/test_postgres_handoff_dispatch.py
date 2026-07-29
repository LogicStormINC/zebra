from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, LeaseLostError
from agent_core.domain.session_handoff import WorkspaceBindingRevision
from agent_core.ports.handoff_dispatch_store import HandoffDispatch
from agent_storage import (
    PostgresHandoffDispatchStore,
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.session_handoff_facts import (
    read_source_facts_in_transaction,
)
from agent_storage.session_handoff_rows import HandoffStorageConflictError
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class _Seed:
    namespace: str
    parent_id: SessionId
    child_id: SessionId
    fence: LeaseFence
    expected_workspace: WorkspaceBindingRevision


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def seed(postgres_dsn: str) -> Generator[_Seed]:
    namespace = f"handoff-dispatch-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    parent_id = SessionId(uuid4())
    child_id = SessionId(uuid4())
    now = datetime.now(UTC)
    workspace = _workspace_row()
    handoff_id = uuid4()
    artifact_id = f"handoff-envelope-{handoff_id}"
    with psycopg.connect(postgres_dsn) as connection:
        for session_id in (parent_id, child_id):
            connection.execute(
                "INSERT INTO session_streams VALUES (%s, %s, 0)",
                (namespace, session_id),
            )
            connection.execute(
                """
                INSERT INTO session_projections (
                    deployment_namespace, session_id, title, status,
                    created_at, updated_at, current_sequence
                ) VALUES (%s, %s, 'handoff', 'ready', %s, %s, 0)
                """,
                (namespace, session_id, now, now),
            )
        connection.execute(
            """
            INSERT INTO workspace_projections (
                deployment_namespace, session_id, workspace_root, prepared_at,
                updated_at, current_sequence, status, policy_profile, tool_profile,
                network_profile, network_allowlist, mcp_allowlist, skill_components
            ) VALUES (%s, %s, %s, %s, %s, 0, 'prepared', %s, 'general',
                      'none', %s, %s, %s)
            """,
            (
                namespace,
                child_id,
                workspace["workspace_root"],
                now,
                now,
                workspace["policy_profile"],
                Jsonb(workspace["network_allowlist"]),
                Jsonb(workspace["mcp_allowlist"]),
                Jsonb(workspace["skill_components"]),
            ),
        )
        connection.execute(
            """
            INSERT INTO handoff_operations (
                deployment_namespace, operation_id, status, source_session_id,
                target_session_id, handoff_id, idempotency_key_hash, request_hash,
                expected_source_stream_version, authority_revision,
                workspace_revision, task_profile_revision, effective_depth_limit,
                artifact_id, created_at, updated_at
            ) VALUES (%s, %s, 'committed', %s, %s, %s, %s, %s, 0, 'authority',
                      %s, 'task', 128, %s, %s, %s)
            """,
            (
                namespace,
                uuid4(),
                parent_id,
                child_id,
                handoff_id,
                "1" * 64,
                "2" * 64,
                Jsonb({"revision_hash": "reserved"}),
                artifact_id,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO session_handoff_envelopes (
                deployment_namespace, handoff_id, source_session_id,
                target_session_id, artifact_id, envelope, checksum, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                namespace,
                handoff_id,
                parent_id,
                child_id,
                artifact_id,
                Jsonb({"handoff_id": str(handoff_id)}),
                "3" * 64,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO handoff_dispatch_outbox (
                deployment_namespace, delivery_id, child_session_id,
                handoff_id, status, created_at
            ) VALUES (%s, %s, %s, %s, 'pending', %s)
            """,
            (namespace, child_id, child_id, handoff_id, now),
        )
    lease = PostgresLeaseStore(postgres_dsn, deployment_namespace=namespace).acquire(
        child_id,
        owner_instance_id="worker-a",
        ttl=timedelta(minutes=5),
    )
    with psycopg.connect(postgres_dsn, row_factory=psycopg.rows.dict_row) as connection:
        revision = read_source_facts_in_transaction(
            connection,
            namespace,
            child_id,
            at=now,
        ).workspace_revision
    yield _Seed(namespace, parent_id, child_id, lease.fence, revision)
    _delete_namespace(postgres_dsn, namespace)


def test_claim_and_ack_use_exact_current_fence(postgres_dsn: str, seed: _Seed) -> None:
    store = _store(postgres_dsn, seed.namespace)
    now = datetime.now(UTC)

    claim = store.claim_for_child(seed.child_id, fence=seed.fence, claimed_at=now)

    assert claim is not None
    assert claim.claim_fence == seed.fence
    assert claim.claim_token is not None
    assert store.claim_for_child(seed.child_id, fence=seed.fence, claimed_at=now) is None
    store.acknowledge(claim, checked_at=now)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            """
            SELECT status, claim_token, acked_at IS NOT NULL
            FROM handoff_dispatch_outbox
            WHERE deployment_namespace = %s AND child_session_id = %s
            """,
            (seed.namespace, seed.child_id),
        ).fetchone() == ("acked", None, True)


def test_reclaim_rotates_token_and_rejects_old_claim(postgres_dsn: str, seed: _Seed) -> None:
    store = _store(postgres_dsn, seed.namespace)
    now = datetime.now(UTC)
    old = store.claim_for_child(seed.child_id, fence=seed.fence, claimed_at=now)
    assert old is not None
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE handoff_dispatch_outbox
            SET claim_expires_at = transaction_timestamp() - interval '1 second'
            WHERE deployment_namespace = %s AND child_session_id = %s
            """,
            (seed.namespace, seed.child_id),
        )
    current = store.claim_for_child(seed.child_id, fence=seed.fence, claimed_at=now)

    assert current is not None and current.claim_token != old.claim_token
    with pytest.raises(HandoffStorageConflictError):
        store.acknowledge(old, checked_at=now)
    store.acknowledge(current, checked_at=now)


def test_same_owner_new_generation_rejects_old_ack(postgres_dsn: str, seed: _Seed) -> None:
    store = _store(postgres_dsn, seed.namespace)
    lease_store = PostgresLeaseStore(postgres_dsn, deployment_namespace=seed.namespace)
    now = datetime.now(UTC)
    claim = store.claim_for_child(seed.child_id, fence=seed.fence, claimed_at=now)
    assert claim is not None
    lease_store.release(seed.child_id, fence=seed.fence)
    replacement = lease_store.acquire(
        seed.child_id,
        owner_instance_id=seed.fence.owner_instance_id,
        ttl=timedelta(minutes=5),
    )

    assert replacement.fence != seed.fence
    with pytest.raises(LeaseLostError):
        store.acknowledge(claim, checked_at=now)


def test_workspace_drift_does_not_ack(postgres_dsn: str, seed: _Seed) -> None:
    store = _store(postgres_dsn, seed.namespace)
    now = datetime.now(UTC)
    claim = store.claim_for_child(seed.child_id, fence=seed.fence, claimed_at=now)
    assert claim is not None
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE workspace_projections SET workspace_root = '/tmp/drifted'
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (seed.namespace, seed.child_id),
        )

    current = store.acknowledge_if_workspace_matches(
        claim,
        expected=seed.expected_workspace,
        checked_at=now,
    )

    assert current != seed.expected_workspace
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            """
            SELECT status FROM handoff_dispatch_outbox
            WHERE deployment_namespace = %s AND child_session_id = %s
            """,
            (seed.namespace, seed.child_id),
        ).fetchone() == ("claimed",)


def test_source_facts_use_database_time_for_active_lease(
    postgres_dsn: str,
    seed: _Seed,
) -> None:
    with psycopg.connect(postgres_dsn, row_factory=psycopg.rows.dict_row) as connection:
        facts = read_source_facts_in_transaction(
            connection,
            seed.namespace,
            seed.child_id,
            at=datetime.now(UTC) + timedelta(days=365),
        )

    assert facts.has_active_lease
    assert facts.lease_fence == seed.fence


def test_workspace_row_is_locked_through_ack(
    postgres_dsn: str,
    seed: _Seed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(postgres_dsn, seed.namespace)
    now = datetime.now(UTC)
    claim = store.claim_for_child(seed.child_id, fence=seed.fence, claimed_at=now)
    assert claim is not None
    revision_read = Event()
    allow_ack = Event()
    original_ack = store._acknowledge

    def paused_ack(connection: Any, receipt: HandoffDispatch) -> int:
        revision_read.set()
        assert allow_ack.wait(timeout=5)
        return original_ack(connection, receipt)

    monkeypatch.setattr(store, "_acknowledge", paused_ack)
    with ThreadPoolExecutor(max_workers=2) as executor:
        ack = executor.submit(
            store.acknowledge_if_workspace_matches,
            claim,
            expected=seed.expected_workspace,
            checked_at=now,
        )
        assert revision_read.wait(timeout=5)
        update = executor.submit(
            _update_workspace_root,
            postgres_dsn,
            seed.namespace,
            seed.child_id,
        )
        with pytest.raises(FutureTimeout):
            update.result(timeout=0.2)
        allow_ack.set()
        assert ack.result(timeout=5) == seed.expected_workspace
        update.result(timeout=5)


def test_envelope_artifact_is_bound_to_committed_operation(
    postgres_dsn: str,
    seed: _Seed,
) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                """
                UPDATE handoff_operations SET artifact_id = 'different-artifact'
                WHERE deployment_namespace = %s AND target_session_id = %s
                """,
                (seed.namespace, seed.child_id),
            )


def _store(dsn: str, namespace: str) -> PostgresHandoffDispatchStore:
    return PostgresHandoffDispatchStore(dsn, deployment_namespace=namespace)


def _update_workspace_root(dsn: str, namespace: str, session_id: SessionId) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            UPDATE workspace_projections SET workspace_root = '/tmp/concurrent-drift'
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (namespace, session_id),
        )


def _workspace_row() -> dict[str, object]:
    return {
        "workspace_root": "/tmp/handoff-child",
        "policy_profile": "workspace_write",
        "network_allowlist": [],
        "mcp_allowlist": [],
        "skill_components": [],
    }


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute("SET LOCAL zebra.allow_handoff_envelope_delete = 'on'")
        for table in (
            "handoff_dispatch_outbox",
            "session_handoff_envelopes",
            "handoff_operations",
            "worker_leases",
            "workspace_projections",
            "session_projections",
            "session_streams",
            "control_plane_epochs",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )
