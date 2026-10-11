"""Body-free command lookup indexes for bounded AG-UI preflight."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.task_replay_headers import HEADER_INDEXES

TASK_REPLAY_HEADER_MIGRATION = Migration(
    version=62,
    name="indexed_task_run_headers",
    statements=HEADER_INDEXES,
)
