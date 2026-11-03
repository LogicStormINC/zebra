"""Operator-only release selection. Execution remains pinned to a Task digest."""

import json
from typing import Any

from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.host_manifest_freeze import load_frozen_manifest

_HEAD = """
    SELECT manifest_digest, manifest_json FROM host_manifest_publications
    WHERE deployment_namespace=%s AND host_app_id=%s AND connector_id=%s
      AND profile_revision=%s ORDER BY release_id DESC LIMIT 1
"""


def publish_host_manifest(
    dsn: str, *, deployment_namespace: str, host_app_id: str, connector_id: str,
    profile_revision: int, manifest_digest: str, manifest_payload: dict[str, Any],
    expected_manifest_digest: str,
) -> None:
    """Append one validated payload, guarded by the expected current release digest."""
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    key = (deployment_namespace, host_app_id, connector_id, profile_revision)
    with database.connect() as connection:
        # ponytail: serialize the infrequent operator publication per connector profile.
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (json.dumps(("host-manifest-publication", *key)),),
        )
        profile = connection.execute(
            """SELECT status, workload_identity_ref, manifest_binding_policy
               FROM host_connector_profiles
               WHERE deployment_namespace=%s AND host_app_id=%s AND connector_id=%s
                 AND profile_revision=%s FOR SHARE""",
            key,
        ).fetchone()
        if profile is None or profile["status"] != "published":
            raise ValueError("manifest publication requires a published connector profile")
        if (
            manifest_payload.get("manifestDigest") != manifest_digest
            or manifest_payload.get("workloadIdentity") != profile["workload_identity_ref"]
            or (profile["manifest_binding_policy"] == "declared"
                and manifest_payload.get("bindingPolicy") != "declared")
        ):
            raise ValueError("manifest publication disagrees with its profile or digest")
        row = connection.execute(_HEAD, key).fetchone()
        if row is None:
            baseline = load_frozen_manifest(
                dsn, deployment_namespace=deployment_namespace, host_app_id=host_app_id,
                connector_id=connector_id, profile_revision=profile_revision,
            )
            current = baseline.get("manifestDigest") if baseline is not None else None
        else:
            current = row["manifest_digest"]
        if current != expected_manifest_digest:
            raise ValueError("current manifest digest changed")
        if current == manifest_digest:
            return
        connection.execute(
            """INSERT INTO host_manifest_publications (
                 deployment_namespace,host_app_id,connector_id,profile_revision,
                 manifest_digest,manifest_json) VALUES (%s,%s,%s,%s,%s,%s)""",
            (*key, manifest_digest, Jsonb(manifest_payload)),
        )
