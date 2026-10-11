"""Additive derived Run progress; legacy preparation is explicit, not a GET."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.worker_progress import progress_schema

WORKER_PROGRESS_MIGRATION = Migration(
    version=70,
    name="bounded_worker_run_progress",
    statements=progress_schema(postgres=True),
)
