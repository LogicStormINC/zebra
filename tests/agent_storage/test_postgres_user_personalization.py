from __future__ import annotations

import os
from collections.abc import Generator
from uuid import uuid4

import psycopg
import pytest
from agent_core.ports.user_personalization import UserPersonalizationConflictError
from agent_storage import apply_postgres_migrations
from agent_storage.postgres.user_personalization import PostgresUserPersonalizationStore
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    value = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not value:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return value


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"user_personalization_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_user_personalization_is_namespaced_and_revision_guarded(dsn: str) -> None:
    store = PostgresUserPersonalizationStore(dsn, deployment_namespace="cloud-a")
    other = PostgresUserPersonalizationStore(dsn, deployment_namespace="cloud-b")

    created = store.put(
        "user-1", "Prefer concise answers.", expected_revision=0, operator="user-1"
    )
    assert created.revision == 1
    assert store.get("user-1") == created
    assert other.get("user-1") is None

    with pytest.raises(UserPersonalizationConflictError):
        store.put("user-1", "Stale", expected_revision=0, operator="user-1")

    cleared = store.clear("user-1", expected_revision=1, operator="user-1")
    assert cleared.instructions is None
    assert cleared.revision == 2
