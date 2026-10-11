"""Bounded native Task origin proof; fresh binding and certification stay separate."""

from typing import Any

from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import SessionEvent

from agent_storage.postgres.coverage_task_summary_migration import (
    COVERAGE_TASK_SUMMARY_MIGRATION as MIGRATION,
)


def admitted_task_origin(
    connection: Any, deployment: str, binding: CoverageRunBinding,
) -> SessionEvent | None:
    row = connection.execute(
        """SELECT p.origin,p.last_sequence,s.current_version,p.task_count
           FROM coverage_task_summary p JOIN session_streams s USING
             (deployment_namespace,session_id)
           WHERE p.deployment_namespace=%s AND p.session_id=%s AND NOT p.invalidated
             AND p.origin->'payload'->'coverage_admission'->>'validation_mode'=
               'final_certification'
             AND EXISTS(SELECT 1 FROM zebra_schema_migrations
               WHERE version=%s AND name=%s AND checksum=%s)""",
        (deployment, binding.session_id, MIGRATION.version, MIGRATION.name, MIGRATION.checksum),
    ).fetchone()
    if row is None:
        return None  # Legacy/unsupported writes never upgrade from mutable projections.
    if row["last_sequence"] != row["current_version"] or not 1 <= row["task_count"] <= 400001:
        raise ValueError("model budget requires unpruned exact Session history")
    event = SessionEvent.model_validate(row["origin"])
    if event.session_id != binding.session_id:
        raise ValueError("persisted strict Task identity changed or disappeared")
    return event
