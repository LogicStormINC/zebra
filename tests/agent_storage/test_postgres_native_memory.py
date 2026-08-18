from __future__ import annotations

import os
from collections.abc import Generator
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import MemoryId
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewaySearchRequest,
    MemoryGatewayStatus,
)
from agent_storage import (
    NativeMemoryConflictError,
    NativeMemoryStaleGenerationError,
    PostgresNativeMemoryGateway,
    apply_postgres_migrations,
)
from agent_storage.postgres.migrations import MIGRATIONS
from psycopg import sql
from psycopg.conninfo import make_conninfo

NAMESPACE = "native-memory-test"
SCOPE = "workspace-a"


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"native_memory_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def gateway(dsn: str) -> PostgresNativeMemoryGateway:
    return PostgresNativeMemoryGateway(dsn, deployment_namespace=NAMESPACE, scope_id=SCOPE)


def test_v12_schema_is_migrated_and_constructor_does_not_run_ddl(dsn: str) -> None:
    with psycopg.connect(dsn) as connection:
        tables = connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name LIKE 'native_memory_%'
            ORDER BY table_name
            """
        ).fetchall()
        version = connection.execute("SELECT max(version) FROM zebra_schema_migrations").fetchone()
    assert [row[0] for row in tables] == [
        "native_memory_authority",
        "native_memory_operations",
        "native_memory_retrieval",
        "native_memory_scopes",
    ]
    assert version == (23,)

    empty_schema = f"native_memory_empty_{uuid4().hex}"
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(empty_schema)))
    empty_dsn = make_conninfo(dsn, options=f"-c search_path={empty_schema}")
    try:
        store = PostgresNativeMemoryGateway(
            empty_dsn,
            deployment_namespace=NAMESPACE,
            scope_id=SCOPE,
        )
        with pytest.raises(psycopg.errors.UndefinedTable):
            store.current_generation()
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(empty_schema))
            )


def test_publish_search_and_idempotent_replay_are_authoritative(
    dsn: str,
    gateway: PostgresNativeMemoryGateway,
) -> None:
    first_id = MemoryId(UUID("00000000-0000-0000-0000-000000000001"))
    first = gateway.publish(_publication(first_id, "operation-1", "zebra setup"))
    replay = gateway.publish(
        _publication(
            MemoryId(UUID("00000000-0000-0000-0000-000000000099")),
            "operation-1",
            "regenerated request",
        )
    )

    assert first.status is MemoryGatewayStatus.SUCCEEDED
    assert first.provider_ref == str(first_id)
    assert replay.status is MemoryGatewayStatus.SUCCEEDED
    assert replay.provider_ref == str(first_id)
    assert replay.detail == "replayed"
    search = gateway.search(MemoryGatewaySearchRequest(namespace=NAMESPACE, query="zebra", limit=5))
    assert search.status is MemoryGatewayStatus.SUCCEEDED
    assert [hit.memory_id for hit in search.hits] == [first_id]
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            """
            SELECT count(*) FROM native_memory_authority
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone() == (1,)
        assert connection.execute(
            """
            SELECT count(*) FROM native_memory_retrieval
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone() == (1,)


def test_operation_lookup_recovers_a_committed_result_after_response_loss(
    gateway: PostgresNativeMemoryGateway,
) -> None:
    memory_id = MemoryId(UUID("00000000-0000-0000-0000-000000000002"))
    gateway.publish(_publication(memory_id, "operation-response-loss", "durable fact"))
    operation = gateway.get_operation("operation-response-loss")
    assert operation is not None
    assert operation.memory_id == memory_id
    assert operation.result_status == "committed"
    retry = gateway.publish(
        _publication(
            MemoryId(UUID("00000000-0000-0000-0000-000000000098")),
            "operation-response-loss",
            "response was lost",
        )
    )
    assert retry.provider_ref == str(memory_id)
    assert retry.detail == "replayed"


def test_projection_failure_rolls_back_authority_and_operation(
    dsn: str,
    gateway: PostgresNativeMemoryGateway,
) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            CREATE FUNCTION fail_native_memory_projection() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'projection build failed';
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER fail_native_memory_projection
            BEFORE INSERT ON native_memory_retrieval
            FOR EACH ROW EXECUTE FUNCTION fail_native_memory_projection()
            """
        )
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="projection build failed"):
            gateway.publish(
                _publication(
                    MemoryId(UUID("00000000-0000-0000-0000-000000000007")),
                    "operation-projection-failure",
                    "must roll back",
                )
            )
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "DROP TRIGGER fail_native_memory_projection ON native_memory_retrieval"
            )
            connection.execute("DROP FUNCTION fail_native_memory_projection()")
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            """
            SELECT count(*) FROM native_memory_authority
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone() == (0,)
        assert connection.execute(
            """
            SELECT count(*) FROM native_memory_operations
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone() == (0,)


def test_generation_cas_reset_and_stale_writer_fence(
    dsn: str,
    gateway: PostgresNativeMemoryGateway,
) -> None:
    old_id = MemoryId(UUID("00000000-0000-0000-0000-000000000003"))
    gateway.publish(_publication(old_id, "operation-old", "old generation"))
    reset = gateway.reset_scope(expected_generation=1)
    assert (reset.previous_generation, reset.generation, reset.deleted_memories) == (1, 2, 1)
    with pytest.raises(NativeMemoryStaleGenerationError):
        gateway.publish_native(
            _publication(
                MemoryId(UUID("00000000-0000-0000-0000-000000000004")),
                "operation-stale",
                "must be fenced",
            ),
            expected_generation=1,
        )
    assert gateway.get_operation("operation-stale") is None
    assert gateway.current_generation() == 2
    assert gateway.recall("old") == ()
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM native_memory_authority WHERE deployment_namespace = %s",
            (NAMESPACE,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM native_memory_operations WHERE deployment_namespace = %s",
            (NAMESPACE,),
        ).fetchone() == (1,)


def test_delete_is_complete_scoped_and_replayable(
    dsn: str,
    gateway: PostgresNativeMemoryGateway,
) -> None:
    memory_id = MemoryId(UUID("00000000-0000-0000-0000-000000000005"))
    gateway.publish(_publication(memory_id, "operation-delete-publish", "remove me"))
    request = MemoryGatewayDeleteRequest(
        memory_id=memory_id,
        namespace=NAMESPACE,
        idempotency_key="operation-delete",
    )
    first = gateway.delete(request)
    replay = gateway.delete(request)
    assert first.status is MemoryGatewayStatus.SUCCEEDED
    assert first.provider_ref == str(memory_id)
    assert replay.status is MemoryGatewayStatus.SUCCEEDED
    assert replay.detail == "replayed"
    assert (
        gateway.search(MemoryGatewaySearchRequest(namespace=NAMESPACE, query="remove")).hits == ()
    )
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM native_memory_authority WHERE memory_id = %s",
            (memory_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM native_memory_retrieval WHERE memory_id = %s",
            (memory_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM native_memory_operations WHERE memory_id = %s",
            (memory_id,),
        ).fetchone() == (2,)


def test_missing_delete_is_a_deterministic_noop(
    gateway: PostgresNativeMemoryGateway,
) -> None:
    request = MemoryGatewayDeleteRequest(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000006")),
        namespace=NAMESPACE,
        idempotency_key="operation-missing-delete",
    )
    first = gateway.delete(request)
    replay = gateway.delete(request)
    assert first.status is MemoryGatewayStatus.NOT_FOUND
    assert replay.status is MemoryGatewayStatus.NOT_FOUND
    assert replay.detail == "replayed"


def test_recall_topic_limit_and_namespace_scope_are_deterministic(
    gateway: PostgresNativeMemoryGateway,
) -> None:
    first_id = MemoryId(UUID("00000000-0000-0000-0000-000000000010"))
    second_id = MemoryId(UUID("00000000-0000-0000-0000-000000000011"))
    gateway.publish_native(
        _publication(first_id, "operation-recall-1", "zebra setup"),
        topic="ops",
    )
    gateway.publish_native(
        _publication(second_id, "operation-recall-2", "zebra setup"),
        topic="docs",
    )
    assert [hit.memory_id for hit in gateway.recall("zebra", limit=1)] == [first_id]
    assert [hit.memory_id for hit in gateway.recall("zebra", topic="docs")] == [second_id]
    wrong_namespace = gateway.search(MemoryGatewaySearchRequest(namespace="other", query="zebra"))
    assert wrong_namespace.status is MemoryGatewayStatus.DEGRADED


def test_cross_scope_and_idempotency_conflicts_fail_closed(
    dsn: str,
    gateway: PostgresNativeMemoryGateway,
) -> None:
    memory_id = MemoryId(UUID("00000000-0000-0000-0000-000000000012"))
    gateway.publish(_publication(memory_id, "operation-conflict", "one"))
    replay = gateway.publish_native(
        _publication(memory_id, "operation-conflict", "same key, replay"),
        topic="other",
    )
    assert replay.replayed
    other_scope = PostgresNativeMemoryGateway(
        dsn,
        deployment_namespace=NAMESPACE,
        scope_id="workspace-b",
    )
    other_id = MemoryId(UUID("00000000-0000-0000-0000-000000000013"))
    with pytest.raises(NativeMemoryConflictError):
        other_scope.publish_native(_publication(other_id, "operation-conflict", "scope collision"))
    other_scope.publish(_publication(other_id, "operation-other-scope", "isolated"))
    assert (
        gateway.search(MemoryGatewaySearchRequest(namespace=NAMESPACE, query="isolated")).hits == ()
    )


def test_v11_upgrade_applies_v12_without_rewriting_history(postgres_dsn: str) -> None:
    schema = f"native_memory_upgrade_{uuid4().hex}"
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
            for migration in MIGRATIONS[:11]:
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
                "SELECT max(version), count(*) FROM zebra_schema_migrations"
            ).fetchone() == (23, 23)
            assert connection.execute(
                "SELECT name FROM zebra_schema_migrations WHERE version = 11"
            ).fetchone() == ("memory_delivery_ledger",)
            assert connection.execute(
                "SELECT name FROM zebra_schema_migrations WHERE version = 23"
            ).fetchone() == ("session_tenant_namespace",)
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _publication(memory_id: MemoryId, operation_id: str, text: str) -> ConfirmedMemoryPublication:
    return ConfirmedMemoryPublication(
        memory_id=memory_id,
        namespace=NAMESPACE,
        text=text,
        idempotency_key=operation_id,
    )
