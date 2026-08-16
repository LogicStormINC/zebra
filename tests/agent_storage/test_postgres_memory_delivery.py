from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryScope,
    MemoryDeliveryScopeState,
)
from agent_storage import (
    MemoryDeliveryConflictError,
    PostgresMemoryDeliveryLedger,
    PostgresMigrationError,
    apply_postgres_migrations,
)
from agent_storage.postgres.governed_memory_rows import memory_values
from agent_storage.postgres.migrations import MIGRATIONS
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"memory_delivery_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def ledger(dsn: str) -> PostgresMemoryDeliveryLedger:
    return PostgresMemoryDeliveryLedger(dsn, deployment_namespace="delivery-test")


def scope(
    digest: str = "a" * 64,
    *,
    generation: int = 1,
    revision: int = 0,
) -> MemoryDeliveryScope:
    return MemoryDeliveryScope(
        deployment_namespace="delivery-test",
        scope_digest=digest,
        generation=generation,
        revision=revision,
    )


def test_v11_scope_isolation_idempotent_enqueue_and_claim(
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    first_scope = scope()
    second_scope = scope("b" * 64)
    first = ledger.enqueue_publish(
        MemoryId(uuid4()),
        memory_revision=2,
        content_digest="c" * 64,
        scope=first_scope,
    )
    replay = ledger.enqueue(first, scope=first_scope)
    second = ledger.enqueue_delete(
        MemoryId(uuid4()),
        memory_revision=3,
        content_digest="d" * 64,
        scope=second_scope,
    )

    assert replay == first
    assert ledger.claim_next(owner="worker-a", scope=first_scope) is not None
    assert ledger.claim_next(owner="worker-b", scope=first_scope) is None
    second_claim = ledger.claim_next(owner="worker-b", scope=second_scope)
    assert second_claim is not None and second_claim.operation.memory_id == second.memory_id


def test_mapping_read_rejects_cross_namespace_scope(
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    with pytest.raises(MemoryDeliveryConflictError, match="namespace"):
        ledger.get_mapping(
            MemoryId(uuid4()),
            scope=MemoryDeliveryScope(
                deployment_namespace="other-deployment",
                scope_digest="a" * 64,
                generation=1,
                revision=0,
            ),
        )


def test_publish_completion_writes_mapping_and_batch_revalidation_is_metadata_only(
    dsn: str,
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    memory_id = MemoryId(uuid4())
    digest = _insert_authority(dsn, memory_id)
    current_scope = scope()
    ledger.enqueue_publish(
        memory_id,
        memory_revision=2,
        content_digest=digest,
        scope=current_scope,
    )
    claim = ledger.claim_next(owner="worker-a", scope=current_scope)
    assert claim is not None
    ledger.mark_in_flight(claim)
    completed = ledger.complete(
        claim,
        certainty=MemoryDeliveryCertainty.APPLIED,
        provider_ref="provider-42",
    )

    assert completed.certainty is MemoryDeliveryCertainty.APPLIED
    admission = ledger.revalidate_search_hits(
        current_scope,
        [(memory_id, "provider-42"), (MemoryId(uuid4()), "missing")],
    )
    assert len(admission) == 1
    assert admission[0].memory_id == memory_id
    assert not hasattr(admission[0], "text")


def test_stale_ack_cannot_write_after_claim_replacement(
    dsn: str,
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    current_scope = scope()
    operation = ledger.enqueue_publish(
        MemoryId(uuid4()),
        memory_revision=1,
        content_digest="f" * 64,
        scope=current_scope,
    )
    old_claim = ledger.claim_next(
        owner="worker-a",
        claim_ttl=timedelta(milliseconds=1),
        scope=current_scope,
    )
    assert old_claim is not None
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT pg_sleep(0.02)")
    new_claim = ledger.claim_next(owner="worker-b", scope=current_scope)
    assert new_claim is not None and new_claim.claim_token != old_claim.claim_token
    with pytest.raises(MemoryDeliveryConflictError):
        ledger.mark_in_flight(old_claim)
    current = ledger.get(operation.idempotency_key)
    assert current is not None and current.state.value == "claimed"


def test_expired_in_flight_becomes_uncertain_instead_of_pending(
    dsn: str,
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    current_scope = scope()
    operation = ledger.enqueue_publish(
        MemoryId(uuid4()),
        memory_revision=1,
        content_digest="7" * 64,
        scope=current_scope,
    )
    claim = ledger.claim_next(
        owner="worker-a",
        claim_ttl=timedelta(milliseconds=100),
        scope=current_scope,
    )
    assert claim is not None
    in_flight = ledger.mark_in_flight(claim)
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT pg_sleep(0.2)")
    expired = ledger.reconcile_expired(scope=current_scope)
    assert tuple(item.idempotency_key for item in expired) == (operation.idempotency_key,)
    assert in_flight.operation.state.value == "in_flight"
    assert ledger.get(operation.idempotency_key).state.value == "uncertain"  # type: ignore[union-attr]


def test_unknown_quarantines_scope_and_blocks_new_enqueue(
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    current_scope = scope()
    operation = ledger.enqueue_publish(
        MemoryId(uuid4()),
        memory_revision=1,
        content_digest="1" * 64,
        scope=current_scope,
    )
    claim = ledger.claim_next(owner="worker-a", scope=current_scope)
    assert claim is not None
    ledger.mark_in_flight(claim)
    uncertain = ledger.mark_uncertain(claim, reason_code="provider_timeout")
    assert uncertain.certainty is MemoryDeliveryCertainty.UNKNOWN
    quarantined = ledger.get_scope(scope_digest=current_scope.scope_digest, generation=1)
    assert quarantined is not None
    assert quarantined.state is MemoryDeliveryScopeState.QUARANTINED
    with pytest.raises(MemoryDeliveryConflictError, match="not active"):
        ledger.enqueue_publish(
            MemoryId(uuid4()),
            memory_revision=2,
            content_digest="2" * 64,
            scope=current_scope,
        )
    current = ledger.get(operation.idempotency_key)
    assert current is not None and current.state.value == "uncertain"


def test_v11_upgrade_and_checksum_gate(postgres_dsn: str) -> None:
    schema = f"memory_delivery_upgrade_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(isolated) as connection:
            connection.execute(
                """
                CREATE TABLE zebra_schema_migrations (
                    version BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for migration in MIGRATIONS[:10]:
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO zebra_schema_migrations (version, name, checksum)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
        apply_postgres_migrations(isolated)
        with psycopg.connect(isolated) as connection:
            assert connection.execute(
                "SELECT version FROM zebra_schema_migrations ORDER BY version"
            ).fetchall()[-1] == (23,)
            connection.execute(
                "UPDATE zebra_schema_migrations SET checksum = 'bad' WHERE version = 11"
            )
        with pytest.raises(PostgresMigrationError, match="checksum"):
            apply_postgres_migrations(isolated)
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_v11_failure_rolls_back_migration_record(postgres_dsn: str) -> None:
    schema = f"memory_delivery_rollback_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(isolated) as connection:
            connection.execute(
                """
                CREATE TABLE zebra_schema_migrations (
                    version BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for migration in MIGRATIONS[:10]:
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO zebra_schema_migrations (version, name, checksum)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
            connection.execute("CREATE TABLE memory_delivery_scopes (sentinel TEXT)")
        with pytest.raises(psycopg.errors.DuplicateTable):
            apply_postgres_migrations(isolated)
        with psycopg.connect(isolated) as connection:
            assert connection.execute(
                "SELECT max(version), count(*) FROM zebra_schema_migrations"
            ).fetchone() == (10, 10)
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _insert_authority(dsn: str, memory_id: MemoryId) -> str:
    record = MemoryRecord(
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        text="authoritative fact",
        confidence=0.9,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        created_at=NOW,
        updated_at=NOW,
    )
    content_digest = canonical_governed_memory_content_hash(record)
    entry = GovernedMemoryEntry(
        deployment_namespace="delivery-test",
        record=record,
        revision=2,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=content_digest,
    )
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO governed_memory_records (
                deployment_namespace, memory_id, revision, memory_type, text,
                confidence, status, visibility, tenant_id, user_id, repo_id,
                authority_issuer, namespace_id, definition_id,
                source_session_id, source_event_start, source_event_end,
                source_commit_sha, superseded_by, expires_at, created_at,
                updated_at, creation_key, content_digest, provenance_digest
            ) VALUES ("""
            + ", ".join(["%s"] * 25)
            + ")",
            memory_values("delivery-test", entry),
        )
    return content_digest
