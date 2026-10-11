"""Transaction-local revision identity, not cached authorization or final proof."""

from typing import Any

from agent_core.domain.coverage_persistence import CoverageRunBinding

from agent_storage.postgres.coverage_model_revision_migration import (
    COVERAGE_MODEL_REVISION_MIGRATION as MIGRATION,
)


def model_revision(
    connection: Any, deployment: str, binding: CoverageRunBinding,
) -> dict[str, str | int] | None:
    # One indexed scope lookup; migration checksum qualifies the tracking contract.
    row = connection.execute(
        """SELECT generation,revision FROM coverage_model_revisions
           WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s
             AND EXISTS (SELECT 1 FROM zebra_schema_migrations
               WHERE version=%s AND name=%s AND checksum=%s)""",
        (deployment, binding.namespace, binding.run_id,
         MIGRATION.version, MIGRATION.name, MIGRATION.checksum),
    ).fetchone()
    return None if row is None else {
        "generation": str(row["generation"]), "revision": row["revision"],
    }
