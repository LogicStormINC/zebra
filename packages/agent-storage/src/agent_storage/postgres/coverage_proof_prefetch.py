"""Bounded same-transaction evidence pages; no durable or cross-phase authority cache."""

from typing import Any, cast

from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.identifiers import ArtifactId

from agent_storage.postgres.coverage_artifacts import _identity

MATERIALIZATION_PAGE_QUERY = """SELECT * FROM session_events WHERE deployment_namespace=%s
    AND (event_id=ANY(%s) OR (event_type='coverage_artifact_materialized'
      AND payload->'metadata'->>'artifact_uri'=ANY(%s)))
    ORDER BY sequence LIMIT %s FOR SHARE"""


def prefetch_proof(artifacts: Any, refs: tuple[str, ...]) -> None:
    prepare = getattr(artifacts, "_prefetch_proof", None)
    if not callable(prepare):
        return
    identifiers = tuple(dict.fromkeys(_identity(ref) for ref in refs))
    for offset in range(0, len(identifiers), 1000):
        prepare(identifiers[offset:offset + 1000])


def locked_page(
    connection: Any, deployment: str, binding: CoverageRunBinding,
    identifiers: tuple[ArtifactId, ...],
) -> tuple[dict[ArtifactId, Any], list[Any]]:
    if not identifiers or len(identifiers) > 1000 or len(set(identifiers)) != len(identifiers):
        raise ValueError("invalid locked evidence page")
    rows = connection.execute(
        """SELECT * FROM artifact_payload_metadata WHERE deployment_namespace=%s
           AND session_id=%s AND artifact_id=ANY(%s) ORDER BY artifact_id FOR UPDATE""",
        (deployment, binding.session_id, list(identifiers)),
    ).fetchall()
    indexed = {row["artifact_id"]: row for row in rows}
    if len(indexed) != len(identifiers):
        raise ValueError("locked evidence page contains missing or foreign Artifacts")
    # Keep both identities and URI lookup, including foreign-session conflicts.
    # A finalized row alone is never canonical materialization authority.
    event_ids = [row["event_id"] for row in rows]
    events = connection.execute(
        MATERIALIZATION_PAGE_QUERY,
        (deployment, event_ids, [f"artifact://{identifier}" for identifier in identifiers],
         2 * len(identifiers) + 1),
    ).fetchall()
    if len(events) > 2 * len(identifiers):
        raise ValueError("locked evidence page has excessive conflicting Events")
    return indexed, events


def materialized_sources(
    artifacts: Any, connection: Any, deployment: str, binding: CoverageRunBinding,
    ref: str, *, event_id: Any = None,
) -> list[Any]:
    reader = getattr(artifacts, "_native_materialized_sources", None)
    if callable(reader):
        return cast(list[Any], reader(
            connection, deployment, binding.session_id, ref, event_id=event_id,
        ))
    if event_id is None:
        return list(connection.execute(
            """SELECT * FROM session_events WHERE deployment_namespace=%s
               AND event_type='coverage_artifact_materialized'
               AND payload->'metadata'->>'artifact_uri'=%s LIMIT 2 FOR SHARE""",
            (deployment, ref),
        ).fetchall())
    return list(connection.execute(
        """SELECT * FROM session_events WHERE deployment_namespace=%s
           AND (event_id=%s OR (event_type='coverage_artifact_materialized'
             AND payload->'metadata'->>'artifact_uri'=%s)) ORDER BY sequence LIMIT 2 FOR SHARE""",
        (deployment, event_id, ref),
    ).fetchall())
