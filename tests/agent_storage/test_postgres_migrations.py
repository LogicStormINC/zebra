from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import new_session_id, new_task_id
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresControlPlaneEpochError,
    PostgresLeaseStore,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    read_control_plane_epoch,
    rotate_control_plane_epoch,
)
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_migration_dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"test_lease_migration_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    yield make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_lease_migration_is_concurrent_repeatable_and_does_not_bootstrap_epoch(
    isolated_migration_dsn: str,
) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(
            executor.map(
                apply_postgres_migrations,
                (isolated_migration_dsn, isolated_migration_dsn),
            )
        )

    with psycopg.connect(isolated_migration_dsn) as connection:
        migrations = connection.execute(
            "SELECT version, name, length(checksum) FROM zebra_schema_migrations ORDER BY version"
        ).fetchall()
        epochs = connection.execute("SELECT count(*) FROM control_plane_epochs").fetchone()
        lease_columns = connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'worker_leases'
            ORDER BY ordinal_position
            """
        ).fetchall()
        outbox_columns = connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'effect_outbox'
            ORDER BY ordinal_position
            """
        ).fetchall()
        outbox_indexes = connection.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = current_schema() AND tablename = 'effect_outbox'
            """
        ).fetchall()
        outbox_constraints = connection.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'effect_outbox'::regclass
            """
        ).fetchall()
        workspace_columns = connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'workspace_projections'
            ORDER BY ordinal_position
            """
        ).fetchall()
        task_constraints = connection.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid IN (
                'agent_tasks'::regclass,
                'execution_segments'::regclass,
                'task_event_index'::regclass
            )
            """
        ).fetchall()
        context_constraints = connection.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid IN (
                'session_events'::regclass,
                'context_capsule_artifacts'::regclass,
                'active_context_projections'::regclass
            )
            """
        ).fetchall()
        artifact_columns = connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'artifact_payload_metadata'
            ORDER BY ordinal_position
            """
        ).fetchall()
        artifact_constraints = connection.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'artifact_payload_metadata'::regclass
            """
        ).fetchall()
        artifact_auxiliary_tables = connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name IN (
                'artifact_payload_mutations',
                'artifact_payload_management_audit'
              )
            ORDER BY table_name
            """
        ).fetchall()
        memory_tables = connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name IN (
                'governed_memory_records',
                'governed_memory_operations',
                'governed_memory_scan_snapshots',
                'governed_memory_scan_items'
              )
            ORDER BY table_name
            """
        ).fetchall()
        memory_constraints = connection.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid IN (
                'governed_memory_records'::regclass,
                'governed_memory_operations'::regclass,
                'governed_memory_scan_snapshots'::regclass,
                'governed_memory_scan_items'::regclass
            )
            """
        ).fetchall()
        memory_indexes = connection.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename IN ('governed_memory_records', 'governed_memory_scan_snapshots')
            """
        ).fetchall()

    assert migrations == [
        (1, "event_and_projection_storage", 64),
        (2, "control_plane_epoch_and_leases", 64),
        (3, "fenced_effect_dispatch_outbox", 64),
        (4, "fenced_workspace_projections", 64),
        (5, "task_and_segment_index", 64),
        (6, "model_and_tool_event_projections", 64),
        (7, "fenced_context_lifecycle", 64),
        (8, "fenced_session_handoff", 64),
        (9, "fenced_artifact_payload_lifecycle", 64),
        (10, "governed_memory_authority", 64),
        (11, "memory_delivery_ledger", 64),
        (12, "native_memory_gateway", 64),
        (13, "fenced_provider_continuation_authority", 64),
        (14, "cloud_control_plane_shared_records", 64),
        (15, "cloud_delivery_transactions", 64),
        (16, "migration_recovery_cutover_guard", 64),
        (17, "host_authority_registry_replay_audit", 64),
        (18, "workspace_control_instances_operations_snapshots", 64),
        (19, "agent_definition_registry", 64),
        (20, "workspace_definition_snapshot_mirror", 64),
        (21, "governed_memory_definition_scope", 64),
        (22, "agent_release_enforcement_mode", 64),
        (23, "session_tenant_namespace", 64),
        (24, "host_connector_registry", 64),
        (25, "task_binding_snapshots", 64),
        (26, "subagent_delegation_links", 64),
        (27, "orchestration_projections", 64),
        (28, "agent_mailbox", 64),
        (29, "research_tool_profile", 64),
    ]
    assert epochs == (0,)
    assert [row[0] for row in lease_columns] == [
        "deployment_namespace",
        "session_id",
        "control_plane_epoch",
        "fencing_token",
        "owner_instance_id",
        "checkpoint",
        "acquired_at",
        "heartbeat_at",
        "expires_at",
        "released_at",
    ]
    assert {
        "deployment_namespace",
        "dispatch_id",
        "execution_session_id",
        "root_session_id",
        "ledger_key",
        "attempt",
        "request_hash",
        "effect_identity",
        "payload_artifact_ref",
        "status",
        "claim_epoch",
        "claim_fencing_token",
        "claim_owner_instance_id",
        "claim_expires_at",
        "intent_event_id",
        "terminal_event_id",
        "result",
        "evidence",
        "evidence_history",
        "retry_key",
        "created_at",
        "updated_at",
    } <= {row[0] for row in outbox_columns}
    assert any(
        all(part in index[0] for part in ("root_session_id", "ledger_key", "attempt"))
        for index in outbox_indexes
    )
    assert any(
        all(part in index[0] for part in ("execution_session_id", "status"))
        for index in outbox_indexes
    )
    constraint_sql = "\n".join(row[0] for row in outbox_constraints)
    assert all(
        part in constraint_sql
        for part in (
            "root_session_id, ledger_key, attempt",
            "claim_epoch IS NOT NULL",
            "claim_fencing_token IS NOT NULL",
            "claim_owner_instance_id IS NOT NULL",
            "claim_expires_at IS NOT NULL",
            "status = 'succeeded'",
            "result IS NOT NULL",
        )
    )
    context_constraint_sql = "".join(row[0] for row in context_constraints).replace(" ", "")
    assert all(
        part in context_constraint_sql
        for part in (
            "UNIQUE(deployment_namespace,session_id,event_id)",
            "UNIQUE(deployment_namespace,session_id,capsule_id,artifact_id)",
            "FOREIGNKEY(deployment_namespace,session_id,compaction_event_id)"
            "REFERENCESsession_events(deployment_namespace,session_id,event_id)",
            "FOREIGNKEY(deployment_namespace,session_id,capsule_event_id)"
            "REFERENCESsession_events(deployment_namespace,session_id,event_id)",
            "FOREIGNKEY(deployment_namespace,session_id,capsule_id,artifact_id)"
            "REFERENCEScontext_capsule_artifacts("
            "deployment_namespace,session_id,capsule_id,artifact_id)",
        )
    )
    assert {
        "artifact_id",
        "session_id",
        "intended_event_sequence",
        "expected_stream_revision",
        "reservation_epoch",
        "reservation_fencing_token",
        "reservation_owner_instance_id",
        "lifecycle_status",
        "lifecycle_revision",
        "object_version",
        "event_id",
        "request_created_at",
        "reserved_at",
        "updated_at",
    } <= {row[0] for row in artifact_columns}
    artifact_constraint_sql = "".join(row[0] for row in artifact_constraints).replace(" ", "")
    assert all(
        part in artifact_constraint_sql
        for part in (
            "staged",
            "finalized",
            "compensated",
            "pruning",
            "pruned",
            "deployment_namespace,session_id,event_sequence,event_id",
            "artifact://",
        )
    )
    assert artifact_auxiliary_tables == [
        ("artifact_payload_management_audit",),
        ("artifact_payload_mutations",),
    ]
    assert memory_tables == [
        ("governed_memory_operations",),
        ("governed_memory_records",),
        ("governed_memory_scan_items",),
        ("governed_memory_scan_snapshots",),
    ]
    memory_constraint_sql = "".join(row[0] for row in memory_constraints).replace(" ", "")
    assert all(
        part in memory_constraint_sql
        for part in (
            "PRIMARYKEY(deployment_namespace,memory_id)",
            "UNIQUE(deployment_namespace,creation_key)",
            "REFERENCESsession_events(deployment_namespace,session_id,sequence)",
            "REFERENCESsession_events(deployment_namespace,session_id,sequence,event_id)",
            "status='deleted'",
            "superseded_by<>memory_id",
        )
    )
    memory_index_sql = "\n".join(row[0] for row in memory_indexes)
    assert "USING gin (search_vector) WHERE (status <> 'deleted'::text)" in memory_index_sql
    assert memory_index_sql.count("UNIQUE INDEX governed_memory_") >= 3
    assert [row[0] for row in workspace_columns] == [
        "deployment_namespace",
        "session_id",
        "workspace_root",
        "prepared_at",
        "updated_at",
        "current_sequence",
        "status",
        "policy_profile",
        "tool_profile",
        "network_profile",
        "network_allowlist",
        "mcp_allowlist",
        "skill_components",
        "last_attempt_number",
        "runtime_name",
        "runtime_engine",
        "runtime_image",
        "runtime_spec_digest",
        "runtime_network_enforcement",
        "runtime_workspace_writable",
        "snapshot_id",
        "snapshot_path",
        "definition_snapshot",
    ]
    task_constraint_sql = "\n".join(row[0] for row in task_constraints)
    assert all(
        part in task_constraint_sql
        for part in (
            "deployment_namespace, task_id, task_sequence",
            "deployment_namespace, task_id, segment_index",
            "deployment_namespace, event_id",
            "task_id, active_segment_id",
            "task_id, predecessor_id",
            "task_id, segment_id",
            "segment_index >= 0",
        )
    )


def test_postgres_lease_constructor_does_not_run_ddl(
    isolated_migration_dsn: str,
) -> None:
    store = PostgresLeaseStore(
        isolated_migration_dsn,
        deployment_namespace="constructor-no-ddl",
    )

    with pytest.raises(errors.UndefinedTable):
        store.get(new_session_id())


def test_postgres_workspace_constructor_does_not_run_ddl(
    isolated_migration_dsn: str,
) -> None:
    store = PostgresWorkspaceProjectionStore(
        isolated_migration_dsn,
        deployment_namespace="constructor-no-ddl",
    )

    with pytest.raises(errors.UndefinedTable):
        store.get_workspace(new_session_id())


def test_postgres_task_constructor_and_reads_do_not_run_ddl(
    isolated_migration_dsn: str,
) -> None:
    store = PostgresAgentTaskStore(
        isolated_migration_dsn,
        deployment_namespace="constructor-no-ddl",
    )

    with pytest.raises(errors.UndefinedTable):
        store.get_task(new_task_id())


def test_epoch_bootstrap_read_and_restore_rotation_are_explicit(
    isolated_migration_dsn: str,
) -> None:
    apply_postgres_migrations(isolated_migration_dsn)
    namespace = f"epoch-{uuid4()}"

    with pytest.raises(PostgresControlPlaneEpochError, match="not bootstrapped"):
        read_control_plane_epoch(
            isolated_migration_dsn,
            deployment_namespace=namespace,
        )
    with pytest.raises(PostgresControlPlaneEpochError, match="before rotation"):
        rotate_control_plane_epoch(
            isolated_migration_dsn,
            deployment_namespace=namespace,
        )

    first = bootstrap_control_plane_epoch(
        isolated_migration_dsn,
        deployment_namespace=namespace,
    )
    assert (
        read_control_plane_epoch(
            isolated_migration_dsn,
            deployment_namespace=namespace,
        )
        == first
    )
    with pytest.raises(PostgresControlPlaneEpochError, match="already bootstrapped"):
        bootstrap_control_plane_epoch(
            isolated_migration_dsn,
            deployment_namespace=namespace,
        )

    second = rotate_control_plane_epoch(
        isolated_migration_dsn,
        deployment_namespace=namespace,
    )
    assert second != first
    assert (
        read_control_plane_epoch(
            isolated_migration_dsn,
            deployment_namespace=namespace,
        )
        == second
    )


def test_lease_acquire_fails_closed_until_epoch_is_bootstrapped(
    isolated_migration_dsn: str,
) -> None:
    apply_postgres_migrations(isolated_migration_dsn)
    store = PostgresLeaseStore(
        isolated_migration_dsn,
        deployment_namespace=f"missing-epoch-{uuid4()}",
    )

    with pytest.raises(PostgresControlPlaneEpochError, match="not bootstrapped"):
        store.acquire(
            new_session_id(),
            owner_instance_id="worker-a",
            ttl=timedelta(seconds=30),
        )
