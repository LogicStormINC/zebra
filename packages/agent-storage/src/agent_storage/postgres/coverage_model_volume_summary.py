"""One native read of sealed incremental volume; legacy never upgrades by counting."""

from typing import Any

from agent_core.domain.coverage_persistence import CoverageRunBinding

from agent_storage.postgres.coverage_model_volume_migration import (
    COVERAGE_MODEL_VOLUME_MIGRATION as MIGRATION,
)


def volume_summary(connection: Any, deployment: str, binding: CoverageRunBinding) -> Any:
    row = connection.execute(
        """SELECT * FROM coverage_model_summary WHERE deployment_namespace=%s
           AND namespace=%s AND run_id=%s AND volume_ready AND NOT invalidated
           AND EXISTS(SELECT 1 FROM zebra_schema_migrations
             WHERE version=%s AND name=%s AND checksum=%s)""",
        (deployment, binding.namespace, binding.run_id,
         MIGRATION.version, MIGRATION.name, MIGRATION.checksum),
    ).fetchone()
    if row is None:
        return None
    if (
        row["session_id"] != binding.session_id or row["initialized"] != 1
        or row["reserved"] != row["calls"]
        or row["receipts"] != row["calls"] - row["unresolved"]
        or row["witnesses"] != row["initialized"] + row["reserved"] + row["receipts"]
        or row["original_count"] != row["receipts"]
        or any(row[name] < 0 for name in
               ("source_bytes", "original_bytes", "original_count", "volume_watermark"))
    ):
        raise ValueError("native MODEL original volume root conflicts")
    return row
