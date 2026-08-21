"""Durable Host manifest freeze store (ADR-017 admission freeze).

Admission freezes each connector profile revision's manifest ONCE;
every later Task references it by digest and the Worker consumes the
frozen copy — no live manifest discovery on the execution path.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


def load_frozen_manifest_by_digest(
    dsn: str,
    *,
    deployment_namespace: str,
    manifest_digest: str,
) -> dict[str, Any] | None:
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT manifest_json FROM host_manifest_freezes
            WHERE deployment_namespace = %s AND manifest_digest = %s
            """,
            (deployment_namespace, manifest_digest),
        ).fetchone()
    return dict(row["manifest_json"]) if row is not None else None


def load_frozen_manifest(
    dsn: str,
    *,
    deployment_namespace: str,
    connector_id: str,
    profile_revision: int,
) -> dict[str, Any] | None:
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT manifest_json FROM host_manifest_freezes
            WHERE deployment_namespace = %s AND connector_id = %s
                AND profile_revision = %s
            """,
            (deployment_namespace, connector_id, profile_revision),
        ).fetchone()
    return dict(row["manifest_json"]) if row is not None else None


def store_frozen_manifest(
    dsn: str,
    *,
    deployment_namespace: str,
    manifest_digest: str,
    connector_id: str,
    profile_revision: int,
    manifest_payload: dict[str, Any],
) -> None:
    """Persist one immutable freeze; an existing row for the revision wins."""

    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        existing = connection.execute(
            """
            SELECT manifest_digest FROM host_manifest_freezes
            WHERE deployment_namespace = %s AND connector_id = %s
                AND profile_revision = %s
            """,
            (deployment_namespace, connector_id, profile_revision),
        ).fetchone()
        if existing is not None:
            if existing["manifest_digest"] != manifest_digest:
                raise ValueError(
                    "connector profile revision is immutable but its frozen "
                    "manifest digest changed; failing closed"
                )
            return
        connection.execute(
            """
            INSERT INTO host_manifest_freezes (
                deployment_namespace, manifest_digest, connector_id,
                profile_revision, manifest_json, fetched_at
            ) VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (deployment_namespace, manifest_digest) DO NOTHING
            """,
            (
                deployment_namespace,
                manifest_digest,
                connector_id,
                profile_revision,
                Jsonb(manifest_payload),
            ),
        )
