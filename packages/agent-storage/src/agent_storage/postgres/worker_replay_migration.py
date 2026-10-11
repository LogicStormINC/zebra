"""v76 indexed bounded canonical Worker authority and Memory replay."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.worker_replay_reader import WORKER_REPLAY_INDEX_SQL

WORKER_REPLAY_MIGRATION = Migration(
    version=76,
    name="bounded_worker_replay_index",
    statements=(WORKER_REPLAY_INDEX_SQL,),
)
