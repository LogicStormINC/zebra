from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

NAMESPACE_A = "authority-a"
NAMESPACE_B = "authority-b"
SCOPE = "workspace-memory"

SCHEMA_DDL = (
    """
    CREATE TABLE native_memory_scopes (
        namespace_id TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        current_generation BIGINT NOT NULL CHECK (current_generation >= 1),
        PRIMARY KEY (namespace_id, scope_id)
    )
    """,
    """
    CREATE TABLE native_memory_operations (
        namespace_id TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        memory_id UUID NOT NULL,
        result_status TEXT NOT NULL DEFAULT 'committed' CHECK (result_status = 'committed'),
        committed_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
        PRIMARY KEY (namespace_id, operation_id)
    )
    """,
    """
    CREATE TABLE native_memory_authority (
        namespace_id TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        generation BIGINT NOT NULL CHECK (generation >= 1),
        memory_id UUID NOT NULL,
        operation_id TEXT NOT NULL,
        content TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        topic TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('confirmed', 'deleted')),
        deleted_at TIMESTAMPTZ,
        PRIMARY KEY (namespace_id, memory_id),
        UNIQUE (namespace_id, operation_id),
        FOREIGN KEY (namespace_id, scope_id)
            REFERENCES native_memory_scopes (namespace_id, scope_id)
    )
    """,
    """
    CREATE TABLE native_memory_retrieval (
        namespace_id TEXT NOT NULL,
        memory_id UUID NOT NULL,
        scope_id TEXT NOT NULL,
        generation BIGINT NOT NULL,
        document TSVECTOR NOT NULL,
        embedding BYTEA NOT NULL,
        PRIMARY KEY (namespace_id, memory_id),
        FOREIGN KEY (namespace_id, memory_id)
            REFERENCES native_memory_authority (namespace_id, memory_id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX native_memory_retrieval_document_idx
    ON native_memory_retrieval USING GIN (document)
    """,
)


class StaleGeneration(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishResult:
    memory_id: UUID
    replayed: bool


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"native_mem_admission_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    with psycopg.connect(isolated) as connection:
        for statement in SCHEMA_DDL:
            connection.execute(statement)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_deterministic_identity_and_idempotent_operation_replay(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)
    memory_id = UUID("00000000-0000-0000-0000-000000000001")

    first = _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-identity-1",
        memory_id=memory_id,
        content="deterministic identity",
    )
    replay = _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-identity-1",
        memory_id=UUID("00000000-0000-0000-0000-000000000099"),
        content="regenerated request must not create a second row",
    )

    assert first == PublishResult(memory_id, replayed=False)
    assert replay == PublishResult(memory_id, replayed=True)
    assert _count(dsn, "native_memory_authority", NAMESPACE_A) == 1
    assert _count(dsn, "native_memory_retrieval", NAMESPACE_A) == 1


def test_ambiguous_commit_response_loss_recovers_one_committed_result(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)
    memory_id = UUID("00000000-0000-0000-0000-000000000002")

    _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-response-loss",
        memory_id=memory_id,
        content="committed before the response disappeared",
    )
    with pytest.raises(ConnectionError, match="response lost"):
        raise ConnectionError("response lost after PostgreSQL COMMIT")

    recovered = _operation_result(dsn, NAMESPACE_A, "operation-response-loss")
    retry = _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-response-loss",
        memory_id=UUID("00000000-0000-0000-0000-000000000098"),
        content="retry payload is not authoritative",
    )

    assert recovered == memory_id
    assert retry == PublishResult(memory_id, replayed=True)
    assert _count(dsn, "native_memory_authority", NAMESPACE_A) == 1
    assert _count(dsn, "native_memory_retrieval", NAMESPACE_A) == 1


def test_authority_and_retrieval_projection_commit_atomically(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)
    _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-atomic-success",
        memory_id=UUID("00000000-0000-0000-0000-000000000003"),
        content="authority and retrieval commit together",
    )

    assert _count(dsn, "native_memory_authority", NAMESPACE_A) == 1
    assert _count(dsn, "native_memory_retrieval", NAMESPACE_A) == 1


def test_precommit_failure_rolls_back_authority_and_projection(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)

    with pytest.raises(RuntimeError, match="projection build failed"):
        _publish(
            dsn,
            namespace=NAMESPACE_A,
            operation_id="operation-atomic-rollback",
            memory_id=UUID("00000000-0000-0000-0000-000000000004"),
            content="must not survive rollback",
            fail_after_authority=True,
        )

    assert _count(dsn, "native_memory_authority", NAMESPACE_A) == 0
    assert _count(dsn, "native_memory_retrieval", NAMESPACE_A) == 0
    assert _count(dsn, "native_memory_operations", NAMESPACE_A) == 0


def test_stale_generation_writer_is_rejected_after_reset(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)
    _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-before-reset",
        memory_id=UUID("00000000-0000-0000-0000-000000000005"),
        content="old generation",
    )
    assert _reset_scope(dsn, NAMESPACE_A) == 2

    with pytest.raises(StaleGeneration):
        _publish(
            dsn,
            namespace=NAMESPACE_A,
            operation_id="operation-stale-writer",
            memory_id=UUID("00000000-0000-0000-0000-000000000006"),
            content="stale writer must be rejected",
            expected_generation=1,
        )

    assert _operation_result(dsn, NAMESPACE_A, "operation-stale-writer") is None
    assert _count(dsn, "native_memory_authority", NAMESPACE_A) == 0


def test_scoped_reset_removes_all_content_bearing_rows_and_keeps_audit(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)
    for index in (7, 8):
        _publish(
            dsn,
            namespace=NAMESPACE_A,
            operation_id=f"operation-reset-{index}",
            memory_id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
            content=f"content-bearing memory {index}",
        )

    assert _reset_scope(dsn, NAMESPACE_A) == 2
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM native_memory_authority WHERE namespace_id = %s",
            (NAMESPACE_A,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM native_memory_retrieval WHERE namespace_id = %s",
            (NAMESPACE_A,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM native_memory_operations WHERE namespace_id = %s",
            (NAMESPACE_A,),
        ).fetchone() == (2,)


def test_scoped_reset_isolated_by_namespace(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)
    _seed_scope(dsn, NAMESPACE_B)
    memory_id = UUID("00000000-0000-0000-0000-000000000009")
    _publish(
        dsn, namespace=NAMESPACE_A, operation_id="operation-a", memory_id=memory_id, content="A"
    )
    _publish(
        dsn, namespace=NAMESPACE_B, operation_id="operation-b", memory_id=memory_id, content="B"
    )

    assert _reset_scope(dsn, NAMESPACE_A) == 2
    assert _count(dsn, "native_memory_authority", NAMESPACE_A) == 0
    assert _count(dsn, "native_memory_authority", NAMESPACE_B) == 1
    assert _recall(dsn, NAMESPACE_B, "B") == (memory_id,)


def test_minimum_recall_filters_scope_generation_and_limits_deterministically(dsn: str) -> None:
    _seed_scope(dsn, NAMESPACE_A)
    first = UUID("00000000-0000-0000-0000-000000000010")
    second = UUID("00000000-0000-0000-0000-000000000011")
    deleted = UUID("00000000-0000-0000-0000-000000000012")
    _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-recall-1",
        memory_id=first,
        content="zebra setup",
        topic="ops",
    )
    _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-recall-2",
        memory_id=second,
        content="zebra setup",
        topic="ops",
    )
    _publish(
        dsn,
        namespace=NAMESPACE_A,
        operation_id="operation-recall-3",
        memory_id=deleted,
        content="zebra setup",
        topic="ops",
    )
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            UPDATE native_memory_authority
            SET status = 'deleted', deleted_at = transaction_timestamp()
            WHERE namespace_id = %s AND memory_id = %s
            """,
            (NAMESPACE_A, deleted),
        )

    assert _recall(dsn, NAMESPACE_A, "zebra", top_k=1, topic="ops") == (first,)
    assert _recall(dsn, NAMESPACE_A, "zebra", top_k=10, topic="ops") == (first, second)


def _seed_scope(dsn: str, namespace: str, *, generation: int = 1) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO native_memory_scopes
            (namespace_id, scope_id, current_generation)
            VALUES (%s, %s, %s)
            """,
            (namespace, SCOPE, generation),
        )


def _publish(
    dsn: str,
    *,
    namespace: str,
    operation_id: str,
    memory_id: UUID,
    content: str,
    expected_generation: int = 1,
    memory_type: str = "preference",
    topic: str = "general",
    fail_after_authority: bool = False,
) -> PublishResult:
    with psycopg.connect(dsn) as connection:
        with connection.transaction():
            existing = connection.execute(
                """
                SELECT memory_id FROM native_memory_operations
                WHERE namespace_id = %s AND operation_id = %s
                """,
                (namespace, operation_id),
            ).fetchone()
            if existing is not None:
                return PublishResult(existing[0], replayed=True)
            current = connection.execute(
                """
                SELECT current_generation FROM native_memory_scopes
                WHERE namespace_id = %s AND scope_id = %s FOR UPDATE
                """,
                (namespace, SCOPE),
            ).fetchone()
            if current is None or current[0] != expected_generation:
                raise StaleGeneration(expected_generation)
            connection.execute(
                """
                INSERT INTO native_memory_operations
                (namespace_id, operation_id, memory_id)
                VALUES (%s, %s, %s)
                """,
                (namespace, operation_id, memory_id),
            )
            connection.execute(
                """
                INSERT INTO native_memory_authority
                (namespace_id, scope_id, generation, memory_id, operation_id,
                 content, memory_type, topic, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')
                """,
                (
                    namespace,
                    SCOPE,
                    expected_generation,
                    memory_id,
                    operation_id,
                    content,
                    memory_type,
                    topic,
                ),
            )
            if fail_after_authority:
                raise RuntimeError("projection build failed")
            connection.execute(
                """
                INSERT INTO native_memory_retrieval
                (namespace_id, memory_id, scope_id, generation, document, embedding)
                VALUES (%s, %s, %s, %s, to_tsvector('simple', %s), %s)
                """,
                (
                    namespace,
                    memory_id,
                    SCOPE,
                    expected_generation,
                    f"{content} {topic}",
                    b"embedding",
                ),
            )
    return PublishResult(memory_id, replayed=False)


def _reset_scope(dsn: str, namespace: str) -> int:
    with psycopg.connect(dsn) as connection:
        with connection.transaction():
            row = connection.execute(
                """
                SELECT current_generation FROM native_memory_scopes
                WHERE namespace_id = %s AND scope_id = %s FOR UPDATE
                """,
                (namespace, SCOPE),
            ).fetchone()
            assert row is not None
            next_generation = int(row[0]) + 1
            connection.execute(
                """
                UPDATE native_memory_scopes SET current_generation = %s
                WHERE namespace_id = %s AND scope_id = %s
                """,
                (next_generation, namespace, SCOPE),
            )
            connection.execute(
                """
                DELETE FROM native_memory_retrieval
                WHERE namespace_id = %s AND scope_id = %s AND generation < %s
                """,
                (namespace, SCOPE, next_generation),
            )
            connection.execute(
                """
                DELETE FROM native_memory_authority
                WHERE namespace_id = %s AND scope_id = %s AND generation < %s
                """,
                (namespace, SCOPE, next_generation),
            )
    return next_generation


def _operation_result(dsn: str, namespace: str, operation_id: str) -> UUID | None:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT memory_id FROM native_memory_operations
            WHERE namespace_id = %s AND operation_id = %s
            """,
            (namespace, operation_id),
        ).fetchone()
    return None if row is None else row[0]


def _count(dsn: str, table: str, namespace: str) -> int:
    assert table in {
        "native_memory_authority",
        "native_memory_retrieval",
        "native_memory_operations",
    }
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE namespace_id = %s").format(
                sql.Identifier(table)
            ),
            (namespace,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _recall(
    dsn: str,
    namespace: str,
    query: str,
    *,
    top_k: int = 10,
    topic: str | None = None,
) -> tuple[UUID, ...]:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT current_generation FROM native_memory_scopes
            WHERE namespace_id = %s AND scope_id = %s
            """,
            (namespace, SCOPE),
        ).fetchone()
        assert row is not None
        results = connection.execute(
            """
            SELECT a.memory_id
            FROM native_memory_authority a
            JOIN native_memory_retrieval r USING (namespace_id, memory_id)
            WHERE a.namespace_id = %s
              AND a.scope_id = %s
              AND a.generation = %s
              AND a.status = 'confirmed'
              AND a.deleted_at IS NULL
              AND r.document @@ plainto_tsquery('simple', %s)
              AND (%s::text IS NULL OR a.topic = %s::text)
            ORDER BY ts_rank_cd(r.document, plainto_tsquery('simple', %s)) DESC, a.memory_id
            LIMIT %s
            """,
            (namespace, SCOPE, row[0], query, topic, topic, query, top_k),
        ).fetchall()
    return tuple(item[0] for item in results)
