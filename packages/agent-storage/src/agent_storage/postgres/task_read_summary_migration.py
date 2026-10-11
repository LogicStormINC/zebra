"""v72: derived usage/attachment frontiers and indexed immutable reference pages."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.task_read_summary_schema import task_read_summary_schema

TASK_READ_SUMMARY_MIGRATION = Migration(
    version=72,
    name="task_read_summaries",
    statements=task_read_summary_schema(postgres=True),
)
