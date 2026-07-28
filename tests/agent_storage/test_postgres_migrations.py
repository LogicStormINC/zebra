from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import new_session_id
from agent_storage import (
    PostgresControlPlaneEpochError,
    PostgresLeaseStore,
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

    assert migrations == [
        (1, "event_and_projection_storage", 64),
        (2, "control_plane_epoch_and_leases", 64),
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


def test_postgres_lease_constructor_does_not_run_ddl(
    isolated_migration_dsn: str,
) -> None:
    store = PostgresLeaseStore(
        isolated_migration_dsn,
        deployment_namespace="constructor-no-ddl",
    )

    with pytest.raises(errors.UndefinedTable):
        store.get(new_session_id())


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
