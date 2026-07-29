from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryEntry,
    GovernedMemoryManagementContext,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.ports.governed_memory_store import (
    GovernedMemoryScanCursor,
    GovernedMemoryScanQuery,
)
from agent_storage import PostgresGovernedMemoryStore, apply_postgres_migrations
from agent_storage.postgres.governed_memory_rows import memory_values
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)
CURSOR_SIGNING_KEY = b"zebra-governed-memory-test-key-32"


@dataclass(frozen=True)
class _ScanEnvironment:
    dsn: str
    namespace: str
    store: PostgresGovernedMemoryStore


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def scan_environment(postgres_dsn: str) -> Generator[_ScanEnvironment]:
    schema = f"governed_memory_scan_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    namespace = f"memory-scan-{uuid4()}"
    yield _ScanEnvironment(
        dsn=dsn,
        namespace=namespace,
        store=PostgresGovernedMemoryStore(
            dsn,
            deployment_namespace=namespace,
            cursor_signing_key=CURSOR_SIGNING_KEY,
        ),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_snapshot_survives_restart_and_consumes_bounded_membership_pages(
    scan_environment: _ScanEnvironment,
) -> None:
    records = _insert_confirmed(scan_environment, count=5, prefix="snapshot")
    query = _scan_query(limit=2)
    management = _management("memory:snapshot")
    first = scan_environment.store.scan_confirmed(query, management=management)

    assert first.next_cursor is not None
    assert scan_environment.store.scan_confirmed(query, management=management) == first
    late = _insert_confirmed(scan_environment, count=1, prefix="late")[0]
    with psycopg.connect(scan_environment.dsn) as connection:
        skipped_ids = connection.execute(
            """SELECT memory_id FROM governed_memory_scan_items
            WHERE deployment_namespace = %s AND snapshot_id = %s
              AND ordinal IN (2, 3) ORDER BY ordinal""",
            (scan_environment.namespace, first.next_cursor.snapshot_token),
        ).fetchall()
        assert len(skipped_ids) == 2
        connection.execute(
            """UPDATE governed_memory_records
            SET status = 'expired', revision = revision + 1,
                updated_at = updated_at + interval '1 minute'
            WHERE deployment_namespace = %s AND memory_id = ANY(%s)""",
            (scan_environment.namespace, [row[0] for row in skipped_ids]),
        )
    restarted = PostgresGovernedMemoryStore(
        scan_environment.dsn,
        deployment_namespace=scan_environment.namespace,
        cursor_signing_key=CURSOR_SIGNING_KEY,
    )
    second = restarted.scan_confirmed(
        query.model_copy(update={"cursor": first.next_cursor}),
        management=management,
    )
    assert second.entries == ()
    assert second.next_cursor is not None
    third = restarted.scan_confirmed(
        query.model_copy(update={"cursor": second.next_cursor}),
        management=management,
    )

    returned_ids = {
        entry.record.memory_id for entry in (*first.entries, *second.entries, *third.entries)
    }
    assert returned_ids <= {record.memory_id for record in records}
    assert late.memory_id not in returned_ids
    assert len(returned_ids) == 3
    assert third.next_cursor is None


def test_snapshot_cursor_rejects_tampering(
    scan_environment: _ScanEnvironment,
) -> None:
    _insert_confirmed(scan_environment, count=3, prefix="cursor")
    query = _scan_query(limit=1)
    management = _management("memory:cursor")
    first = scan_environment.store.scan_confirmed(query, management=management)
    assert first.next_cursor is not None
    token = first.next_cursor.position_token
    index = len(token) // 2
    changed = "a" if token[index] != "a" else "b"
    tampered = GovernedMemoryScanCursor(
        snapshot_token=first.next_cursor.snapshot_token,
        position_token=f"{token[:index]}{changed}{token[index + 1:]}",
    )

    with pytest.raises(GovernedMemoryConflictError, match="cursor"):
        scan_environment.store.scan_confirmed(
            query.model_copy(update={"cursor": tampered}),
            management=management,
        )


def _insert_confirmed(
    environment: _ScanEnvironment,
    *,
    count: int,
    prefix: str,
) -> tuple[MemoryRecord, ...]:
    records = tuple(
        MemoryRecord(
            memory_id=MemoryId(uuid4()),
            memory_type=MemoryType.PREFERENCE,
            text=f"{prefix}-{index}",
            confidence=0.9,
            status=MemoryStatus.CONFIRMED,
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            created_at=NOW + timedelta(seconds=index),
            updated_at=NOW + timedelta(seconds=index),
        )
        for index in range(count)
    )
    with psycopg.connect(environment.dsn) as connection:
        for record in records:
            entry = GovernedMemoryEntry(
                deployment_namespace=environment.namespace,
                record=record,
                revision=1,
                creation_key=canonical_governed_memory_creation_key(record),
                content_digest=canonical_governed_memory_content_hash(record),
            )
            connection.execute(
                """
                INSERT INTO governed_memory_records (
                    deployment_namespace, memory_id, revision, memory_type, text,
                    confidence, status, visibility, tenant_id, user_id, repo_id,
                    source_session_id, source_event_start, source_event_end,
                    source_commit_sha, superseded_by, expires_at, created_at,
                    updated_at, creation_key, content_digest, provenance_digest
                ) VALUES ("""
                + ", ".join(["%s"] * 22)
                + ")",
                memory_values(environment.namespace, entry),
            )
    return records


def _scan_query(*, limit: int) -> GovernedMemoryScanQuery:
    return GovernedMemoryScanQuery(
        scope=MemoryQuery(
            repo_id="zebra-agent",
            visibility=MemoryVisibility.REPO,
        ),
        limit=limit,
    )


def _management(operation_id: str) -> GovernedMemoryManagementContext:
    return GovernedMemoryManagementContext(
        operation_id=operation_id,
        operator="memory-test",
        reason="validate governed Memory scan authority",
    )
