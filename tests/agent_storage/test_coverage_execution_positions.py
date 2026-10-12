"""v99 permits native allocation, never business mutation or seal resurrection.

All DDL/data lives in the imported opt-in PostgreSQL fixture's UUID schema.
"""
# ruff: noqa: F811

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres import migration_runner
from agent_storage.postgres.coverage_execution_positions_migration import (
    COVERAGE_EXECUTION_POSITIONS_MIGRATION as MIGRATION,
)
from agent_storage.postgres.coverage_membership import membership_descriptor, membership_state
from agent_storage.postgres.coverage_projection import seed_run
from agent_storage.postgres.coverage_transactions import append_coverage_event
from agent_storage.postgres.projection_source_metadata import backfill_projection_source_metadata
from agent_storage.postgres.task_event_positions import backfill_task_event_positions

from tests.agent_storage.test_coverage_model_budget import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_env,
    postgres_dsn,
)
from tests.worker.test_coverage_execution_source import seal, source


@pytest.fixture(autouse=True)
def allocation_schema(request, monkeypatch):
    catalog = migration_runner.MIGRATIONS
    assert MIGRATION.version == 99 and MIGRATION in catalog
    version = getattr(request, "param", 99)
    monkeypatch.setattr(
        migration_runner,
        "MIGRATIONS",
        tuple(migration for migration in catalog if migration.version <= version),
    )

    def upgrade(dsn):
        monkeypatch.setattr(migration_runner, "MIGRATIONS", catalog)
        migration_runner.apply_postgres_migrations(dsn)

    return upgrade


@pytest.fixture
def sealed_run(model_env):
    env = model_env()
    env.database, env.session = env.store._database, env.binding.session_id
    with env.database.connect() as connection:
        event = source(connection, env)
    # The upgrade witness must be a committed v98 receipt, not a v98 attempt
    # to seal before its deferred allocator (the negative case tested below).
    with env.database.connect() as connection:
        seal(connection, env, event)
        version = connection.execute(
            "SELECT max(version) AS version FROM zebra_schema_migrations"
        ).fetchone()["version"]
        # v98's source trigger invalidates membership on deferred allocation;
        # v99 must fix new phases without resurrecting that historical root.
        if version >= 99:
            assert membership_state(connection, NAMESPACE, env.binding) is not None
        else:
            assert version == 98 and membership_state(connection, NAMESPACE, env.binding) is None
    return env, event


def snapshot(connection, env, event):
    return connection.execute(
        "SELECT to_jsonb(e) AS row,coverage_model_event_source(to_jsonb(e)) AS original "
        "FROM session_events e WHERE deployment_namespace=%s AND event_id=%s",
        (NAMESPACE, event),
    ).fetchone()


def allocate(connection, env):
    task = TaskId(env.binding.task_id)
    # Bounded even if maintenance regresses; this fixture has one short segment.
    for operation in (backfill_task_event_positions, backfill_projection_source_metadata):
        for _ in range(32):
            if operation(connection, NAMESPACE, task, limit=8):
                break
        else:
            pytest.fail("native allocation failed to complete within bounded fixture pages")


def pending_phase(connection, env):
    """Native manifest/seed and sealed acceptance before deferred allocation fires."""
    binding = env.binding.model_copy(update={"run_id": f"allocation-{uuid4()}"})
    phase = SimpleNamespace(binding=binding, session=env.session)
    sequence = (
        connection.execute(
            "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
            "AND session_id=%s",
            (NAMESPACE, env.session),
        ).fetchone()["current_version"]
        + 1
    )
    manifest = append_coverage_event(
        connection,
        NAMESPACE,
        binding,
        env.fence,
        sequence,
        EventType.COVERAGE_MANIFEST_COMMITTED,
        {
            "binding": binding.model_dump(mode="json"),
            "expected_count": len(expected_units(binding.contract, env.items)),
            "membership": membership_descriptor(binding, env.items),
        },
    )
    seed_run(connection, NAMESPACE, binding, env.items, manifest.sequence)
    event = source(connection, phase)
    seal(connection, phase, event)
    return phase, event


def test_current99_native_allocation_preserves_sealed_source_and_exact_membership(sealed_run):
    root, _ = sealed_run
    env = root
    with env.database.connect() as connection:
        applied = connection.execute(
            "SELECT name,checksum FROM zebra_schema_migrations WHERE version=99"
        ).fetchone()
        assert applied == {"name": MIGRATION.name, "checksum": MIGRATION.checksum}
        env, event = pending_phase(connection, root)
        before = snapshot(connection, env, event)
        assert before["row"]["task_id"] is None
        membership = membership_state(connection, NAMESPACE, env.binding)
        receipt = connection.execute(
            "SELECT to_jsonb(r) AS row FROM coverage_execution_receipts r WHERE event_id=%s",
            (event,),
        ).fetchone()
        manifest = snapshot(connection, env, membership["manifest_event"])
        assert manifest["row"]["task_id"] is None
        connection.execute("SET CONSTRAINTS session_events_allocate_task_position IMMEDIATE")
        after = snapshot(connection, env, event)
        assert after["original"] == before["original"]
        assert {key for key in after["row"] if after["row"][key] != before["row"][key]} == {
            "task_id",
            "task_sequence",
            "projection_block_start",
        }
        assert after["row"]["task_id"] == str(env.binding.task_id)
        assert after["row"]["task_sequence"] >= 0
        assert after["row"]["projection_block_start"] is not None
        assert (
            snapshot(connection, env, membership["manifest_event"])["original"]
            == (manifest["original"])
        )
        assert membership_state(connection, NAMESPACE, env.binding) == membership
        assert (
            connection.execute(
                "SELECT to_jsonb(r) AS row FROM coverage_execution_receipts r WHERE event_id=%s",
                (event,),
            ).fetchone()
            == receipt
        )
        allocate(connection, root)  # Maintenance retries allocate neither source nor seal twice.
        assert snapshot(connection, env, event) == after
        assert membership_state(connection, NAMESPACE, env.binding) == membership


def test_native_deferred_insert_allocation_can_follow_receipt_seal(sealed_run):
    env, _ = sealed_run
    with env.database.connect() as connection:
        allocate(connection, env)
    with env.database.connect() as connection:
        before = membership_state(connection, NAMESPACE, env.binding)
        event = source(connection, env)
        seal(connection, env, event)
        original = snapshot(connection, env, event)
        assert original["row"]["task_id"] is None
        # Prove the actual initially-deferred allocator, not a caller-crafted UPDATE.
        connection.execute("SET CONSTRAINTS session_events_allocate_task_position IMMEDIATE")
        allocated = snapshot(connection, env, event)
        assert allocated["row"]["task_id"] == str(env.binding.task_id)
        assert allocated["row"]["task_sequence"] >= 0
        assert allocated["row"]["projection_block_start"] is not None
        assert allocated["original"] == original["original"]
        assert membership_state(connection, NAMESPACE, env.binding) == before
    with env.database.connect() as connection:
        assert snapshot(connection, env, event) == allocated


def test_allocation_and_receipt_rollback_restore_source_and_membership(sealed_run):
    env, event = sealed_run
    with env.database.connect() as connection:
        original = snapshot(connection, env, event)
        before = membership_state(connection, NAMESPACE, env.binding)
        with pytest.raises(RuntimeError, match="rollback allocation"), connection.transaction():
            phase, pending = pending_phase(connection, env)
            unassigned = snapshot(connection, phase, pending)
            assert unassigned["row"]["task_id"] is None
            connection.execute("SET CONSTRAINTS session_events_allocate_task_position IMMEDIATE")
            assert snapshot(connection, phase, pending)["row"] != unassigned["row"]
            assert membership_state(connection, NAMESPACE, env.binding) == before
            raise RuntimeError("rollback allocation")
        assert snapshot(connection, env, event) == original
        assert membership_state(connection, NAMESPACE, env.binding) == before
        assert snapshot(connection, phase, pending) is None
        assert membership_state(connection, NAMESPACE, phase.binding) is None
        assert (
            connection.execute(
                "SELECT 1 FROM coverage_execution_receipts WHERE event_id=%s", (pending,)
            ).fetchone()
            is None
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "created_at=created_at",  # True no-op remains sealed.
        "task_id=task_id,task_sequence=task_sequence,projection_block_start=projection_block_start",
        "created_at=created_at+interval '1 microsecond'",
        "payload=payload || '{\"tampered\":true}'::jsonb",
        "actor='tool'",
        "policy_version='tampered'",
        "model_profile='tampered'",
        "event_bytes_bound_v1=coalesce(event_bytes_bound_v1,0)+1",
    ],
)
def test99_seal_still_denies_noop_business_and_other_metadata_changes(sealed_run, mutation):
    env, event = sealed_run
    with env.database.connect() as connection:
        before = snapshot(connection, env, event)
        membership = membership_state(connection, NAMESPACE, env.binding)
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            with connection.transaction():
                connection.execute(
                    "UPDATE session_events SET "
                    + mutation
                    + " WHERE deployment_namespace=%s AND event_id=%s",
                    (NAMESPACE, event),
                )
        assert snapshot(connection, env, event) == before
        assert membership_state(connection, NAMESPACE, env.binding) == membership


@pytest.mark.parametrize("field", ["task", "position", "block"])
def test99_excluded_fields_cannot_bypass_native_allocation_guards(sealed_run, field):
    env, event = sealed_run
    with env.database.connect() as connection:
        allocate(connection, env)
        before = snapshot(connection, env, event)
        assignment, args = {
            "task": ("task_id=%s", (uuid4(),)),
            "position": ("task_sequence=task_sequence+1000", ()),
            "block": ("projection_block_start=projection_block_start+1000", ()),
        }[field]
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable|block"):
            with connection.transaction():
                connection.execute(
                    "UPDATE session_events SET "
                    + assignment
                    + " WHERE deployment_namespace=%s AND event_id=%s",
                    (*args, NAMESPACE, event),
                )
        assert snapshot(connection, env, event) == before


def test99_seal_is_deployment_scoped_even_with_colliding_event_uuid(sealed_run):
    env, event = sealed_run
    foreign = "foreign-execution-position-test"
    with env.database.connect() as connection:
        connection.execute("INSERT INTO session_streams VALUES (%s,%s,0)", (foreign, env.session))
        connection.execute(
            """INSERT INTO session_events
               (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
               SELECT %s,event_id,session_id,0,event_type,payload,actor,created_at
               FROM session_events
               WHERE deployment_namespace=%s AND event_id=%s""",
            (foreign, NAMESPACE, event),
        )
        original = snapshot(connection, env, event)
        connection.execute(
            "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
            "WHERE deployment_namespace=%s AND event_id=%s",
            (foreign, event),
        )
        connection.execute(
            "DELETE FROM session_events WHERE deployment_namespace=%s AND event_id=%s",
            (foreign, event),
        )
        assert snapshot(connection, env, event) == original
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            with connection.transaction():
                connection.execute(
                    "DELETE FROM session_events WHERE deployment_namespace=%s AND event_id=%s",
                    (NAMESPACE, event),
                )


@pytest.mark.parametrize("allocation_schema", [98], indirect=True)
def test98_to99_preserves_original_receipt_and_unblocks_only_native_allocation(
    sealed_run,
    allocation_schema,
):
    env, event = sealed_run
    with env.database.connect() as connection:
        original = snapshot(connection, env, event)
        membership = membership_state(connection, NAMESPACE, env.binding)
        receipt = connection.execute(
            "SELECT to_jsonb(r) AS row FROM coverage_execution_receipts r"
        ).fetchone()
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            with connection.transaction():
                source_event = source(connection, env)
                seal(connection, env, source_event)
                connection.execute(
                    "SET CONSTRAINTS session_events_allocate_task_position IMMEDIATE"
                )
        assert snapshot(connection, env, event) == original
        assert membership_state(connection, NAMESPACE, env.binding) == membership
        historic = connection.execute(
            "SELECT version,name,checksum FROM zebra_schema_migrations ORDER BY version"
        ).fetchall()
    allocation_schema(env.dsn)
    with env.database.connect() as connection:
        assert (
            connection.execute(
                "SELECT version,name,checksum FROM zebra_schema_migrations "
                "WHERE version<99 ORDER BY version"
            ).fetchall()
            == historic
        )
        assert snapshot(connection, env, event) == original
        assert membership_state(connection, NAMESPACE, env.binding) == membership
        assert (
            connection.execute(
                "SELECT to_jsonb(r) AS row FROM coverage_execution_receipts r"
            ).fetchone()
            == receipt
        )
        pending = source(connection, env)
        seal(connection, env, pending)
        unassigned = snapshot(connection, env, pending)
        assert unassigned["row"]["task_id"] is None
        connection.execute("SET CONSTRAINTS session_events_allocate_task_position IMMEDIATE")
        allocated = snapshot(connection, env, pending)
        assert allocated["row"]["task_id"] == str(env.binding.task_id)
        assert allocated["original"] == unassigned["original"]
        assert snapshot(connection, env, event)["original"] == original["original"]
        assert membership_state(connection, NAMESPACE, env.binding) == membership


@pytest.mark.parametrize("allocation_schema", [98], indirect=True)
def test99_upgrade_never_resurrects_previously_invalidated_membership(
    sealed_run,
    allocation_schema,
):
    env, event = sealed_run
    with env.database.connect() as connection:
        connection.execute("UPDATE coverage_units SET ordinal=ordinal+100")
        connection.execute("UPDATE coverage_units SET ordinal=ordinal-100")
        assert membership_state(connection, NAMESPACE, env.binding) is None
        original = snapshot(connection, env, event)
    allocation_schema(env.dsn)
    with env.database.connect() as connection:
        assert membership_state(connection, NAMESPACE, env.binding) is None
        allocate(connection, env)
        assert snapshot(connection, env, event)["original"] == original["original"]
        assert membership_state(connection, NAMESPACE, env.binding) is None
