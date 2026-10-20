"""Immutable Host manifest revisions, with unchanged historical digest lookup."""

from __future__ import annotations

import json
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
        rows = connection.execute(
            """SELECT manifest_json FROM host_manifest_freezes
               WHERE deployment_namespace=%s AND manifest_digest=%s
               UNION SELECT manifest_json FROM host_manifest_revisions
               WHERE deployment_namespace=%s AND manifest_digest=%s""",
            (deployment_namespace, manifest_digest, deployment_namespace, manifest_digest),
        ).fetchall()
    if len(rows) > 1:
        raise ValueError("frozen manifest digest has conflicting contents; failing closed")
    return dict(rows[0]["manifest_json"]) if rows else None


def _legacy_revision(
    connection: Any, namespace: str, connector: str, revision: int, host: str | None,
) -> Any:
    row = connection.execute(
        """SELECT manifest_digest,manifest_json FROM host_manifest_freezes
           WHERE deployment_namespace=%s AND connector_id=%s AND profile_revision=%s""",
        (namespace, connector, revision),
    ).fetchone()
    if row is not None and host is not None:
        owners = connection.execute(
            """SELECT host_app_id FROM host_connector_profiles
               WHERE deployment_namespace=%s AND connector_id=%s AND profile_revision=%s""",
            (namespace, connector, revision),
        ).fetchall()
        # Old rows lack Host identity: only a unique registered owner proves the association.
        if [owner["host_app_id"] for owner in owners] != [host]:
            raise ValueError("legacy frozen manifest Host ownership is ambiguous; failing closed")
    return row


def load_frozen_manifest(
    dsn: str,
    *,
    deployment_namespace: str,
    connector_id: str,
    profile_revision: int,
    host_app_id: str | None = None,
) -> dict[str, Any] | None:
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT manifest_json FROM host_manifest_revisions
               WHERE deployment_namespace=%s AND connector_id=%s AND profile_revision=%s
                 AND (%s::text IS NULL OR host_app_id=%s)""",
            (deployment_namespace, connector_id, profile_revision, host_app_id, host_app_id),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("frozen manifest requires explicit Host identity; failing closed")
        if rows:
            return dict(rows[0]["manifest_json"])
        row = _legacy_revision(
            connection, deployment_namespace, connector_id, profile_revision, host_app_id,
        )
    return dict(row["manifest_json"]) if row is not None else None


def store_frozen_manifest(
    dsn: str,
    *,
    deployment_namespace: str,
    manifest_digest: str,
    connector_id: str,
    profile_revision: int,
    manifest_payload: dict[str, Any],
    host_app_id: str | None = None,
) -> None:
    """Atomic first writer wins; never return success for an unpersisted revision.

    Host-less callers retain the historical table/API. Production admission supplies
    Host identity and uses the additive table; old rows and their bytes stay intact.
    """
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    with database.connect() as connection:
        # ponytail: serialize one connector revision across Hosts and both table generations.
        lock_key = json.dumps(
            ["host-manifest-revision", deployment_namespace, connector_id, profile_revision]
        )
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,),
        )
        if host_app_id is None:
            scoped = connection.execute(
                """SELECT manifest_digest FROM host_manifest_revisions
                   WHERE deployment_namespace=%s AND connector_id=%s AND profile_revision=%s""",
                (deployment_namespace, connector_id, profile_revision),
            ).fetchall()
            if len(scoped) > 1:
                raise ValueError("frozen manifest requires explicit Host identity; failing closed")
            if scoped:
                if scoped[0]["manifest_digest"] != manifest_digest:
                    raise ValueError("frozen manifest revision conflict; failing closed")
                return
        existing = _legacy_revision(
            connection, deployment_namespace, connector_id, profile_revision, host_app_id,
        )
        if existing is not None:
            if existing["manifest_digest"] != manifest_digest:
                raise ValueError("frozen manifest revision digest changed; failing closed")
            if host_app_id is None:
                return
        if host_app_id is None:
            connection.execute(
                """INSERT INTO host_manifest_freezes (
                     deployment_namespace,manifest_digest,connector_id,profile_revision,
                     manifest_json,fetched_at) VALUES (%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT DO NOTHING""",
                (deployment_namespace, manifest_digest, connector_id, profile_revision,
                 Jsonb(manifest_payload)),
            )
            row = _legacy_revision(
                connection, deployment_namespace, connector_id, profile_revision, None,
            )
        else:
            connection.execute(
                """INSERT INTO host_manifest_revisions (
                     deployment_namespace,host_app_id,connector_id,profile_revision,
                     manifest_digest,manifest_json) VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (deployment_namespace, host_app_id, connector_id, profile_revision,
                 manifest_digest, Jsonb(manifest_payload)),
            )
            row = connection.execute(
                """SELECT manifest_digest FROM host_manifest_revisions
                   WHERE deployment_namespace=%s AND host_app_id=%s
                     AND connector_id=%s AND profile_revision=%s""",
                (deployment_namespace, host_app_id, connector_id, profile_revision),
            ).fetchone()
        if row is None or row["manifest_digest"] != manifest_digest:
            raise ValueError("frozen manifest revision conflict; failing closed")
