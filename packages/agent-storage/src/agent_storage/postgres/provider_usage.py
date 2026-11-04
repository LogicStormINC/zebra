"""Read recorded provider attempts under one exact Agent publication scope."""

from datetime import datetime, timedelta
from typing import Any

from agent_core.application.task_model_usage import TOKEN_USAGE_FIELDS, advance_model_usage
from agent_core.domain.identifiers import AgentDefinitionId
from agent_core.domain.runtime_bundle_types import BundleScope
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase

_MAX_ATTEMPTS = 10_000


def read_provider_usage(
    database: PostgresDatabase,
    *,
    scope: BundleScope,
    definition_id: AgentDefinitionId,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    if (
        start.utcoffset() is None
        or end.utcoffset() is None
        or not timedelta(0) < end - start <= timedelta(days=31)
    ):
        raise ValueError("usage requires a timezone-aware window of at most 31 days")
    with database.connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '2s'")
        rows = connection.execute(
            """
            WITH attempts AS (
                SELECT session_id, sequence, payload
                FROM session_events
                WHERE deployment_namespace = %(namespace)s
                  AND event_type = 'provider_usage_observed'
                  AND payload->>'phase' = 'started'
                  AND payload->>'definition_id' = %(definition)s
                  AND payload->'bundle_scope' = %(scope)s
                  AND created_at >= %(start)s AND created_at < %(end)s
                LIMIT %(limit)s
            )
            SELECT a.session_id, a.payload->>'attempt_id' AS attempt_id,
                   b.snapshot_json#>>'{host_capability,authority_issuer}' AS issuer,
                   b.snapshot_json#>>'{host_capability,namespace_id}' AS namespace,
                   b.snapshot_json#>>'{host_capability,host_app_id}' AS host_app_id,
                   b.snapshot_json#>>'{host_capability,verified_subject_ref}' AS subject,
                   f.usage, coalesce(f.matches, 0) AS matches
            FROM attempts a
            LEFT JOIN execution_segments s ON s.deployment_namespace = %(namespace)s
                AND s.session_id = a.session_id AND s.task_id::text = a.payload->>'task_id'
            LEFT JOIN task_binding_snapshots b ON b.deployment_namespace = s.deployment_namespace
                AND b.task_id = s.task_id
                AND b.binding_revision::text = a.payload->>'binding_revision'
            LEFT JOIN LATERAL (
                SELECT e.payload->'usage' AS usage, count(*) OVER () AS matches
                FROM session_events e
                WHERE e.deployment_namespace = %(namespace)s AND e.session_id = a.session_id
                  AND e.sequence > a.sequence
                  AND e.event_type = 'provider_usage_observed'
                  AND e.payload->>'phase' = 'finished'
                  AND e.payload - 'phase' - 'usage' = a.payload - 'phase' - 'usage'
                LIMIT 1
            ) f ON TRUE
            """,
            {
                "namespace": database.deployment_namespace,
                "definition": str(definition_id),
                "scope": Jsonb(scope.model_dump(mode="json")),
                "start": start,
                "end": end,
                "limit": _MAX_ATTEMPTS + 1,
            },
        ).fetchall()
    if len(rows) > _MAX_ATTEMPTS:
        raise ValueError("usage window exceeds attempt limit")
    return _summarize(rows)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total: dict[str, Any] = {}
    users: dict[tuple[str, ...], dict[str, Any]] = {}
    seen = set()
    for row in rows:
        key = (row["session_id"], row["attempt_id"])
        if key in seen or row["matches"] > 1:
            raise ValueError("ambiguous provider attempt history")
        seen.add(key)
        identity = (
            (row["issuer"], row["namespace"], row["host_app_id"], row["subject"])
            if row["subject"] is not None
            else ()
        )
        usage = row["usage"] or {}
        total = advance_model_usage(total, usage)
        users[identity] = advance_model_usage(users.get(identity, {}), usage)
    return {
        "total": _counts(total),
        "users": [
            {
                "identity": dict(
                    zip(("issuer", "namespace", "host_app_id", "subject"), identity, strict=True)
                )
                if identity
                else None,
                **_counts(usage),
            }
            for identity, usage in sorted(users.items())
        ],
    }


def _counts(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempt_count": usage.get("model_call_count", 0),
        "tokens": usage.get("provider_token_totals", dict.fromkeys(TOKEN_USAGE_FIELDS)),
    }
