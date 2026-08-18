"""Explicit PostgreSQL control-plane epoch bootstrap and restore rotation."""

from uuid import UUID, uuid4

from psycopg import errors

from agent_storage.postgres.database import PostgresDatabase


class PostgresControlPlaneEpochError(RuntimeError):
    """Raised when epoch authority is missing or an unsafe bootstrap is attempted."""


def bootstrap_control_plane_epoch(dsn: str, *, deployment_namespace: str) -> UUID:
    """Create one namespace epoch without rotating an existing authority."""
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    candidate = uuid4()
    try:
        with database.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO control_plane_epochs (deployment_namespace, epoch)
                VALUES (%s, %s)
                RETURNING epoch
                """,
                (database.deployment_namespace, candidate),
            ).fetchone()
    except errors.UniqueViolation as exc:
        raise PostgresControlPlaneEpochError(
            "control-plane epoch is already bootstrapped; rotate after restore"
        ) from exc
    if row is None:  # pragma: no cover - INSERT RETURNING is exhaustive
        raise PostgresControlPlaneEpochError("control-plane epoch bootstrap failed")
    return UUID(str(row["epoch"]))


def read_control_plane_epoch(dsn: str, *, deployment_namespace: str) -> UUID:
    """Read the current epoch without granting runtime authority to change it."""
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT epoch FROM control_plane_epochs WHERE deployment_namespace = %s
            """,
            (database.deployment_namespace,),
        ).fetchone()
    if row is None:
        raise PostgresControlPlaneEpochError("control-plane epoch is not bootstrapped")
    return UUID(str(row["epoch"]))


def rotate_control_plane_epoch(dsn: str, *, deployment_namespace: str) -> UUID:
    """Issue a fresh epoch after restore, before runtime writers are enabled."""
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    next_epoch = uuid4()
    with database.connect() as connection:
        row = connection.execute(
            """
            UPDATE control_plane_epochs
            SET epoch = %s, updated_at = transaction_timestamp()
            WHERE deployment_namespace = %s
            RETURNING epoch
            """,
            (next_epoch, database.deployment_namespace),
        ).fetchone()
    if row is None:
        raise PostgresControlPlaneEpochError(
            "control-plane epoch must be bootstrapped before rotation"
        )
    return UUID(str(row["epoch"]))
