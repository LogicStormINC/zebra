"""Additive v69: bounded Session observation fields; no implicit legacy backfill."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.session_observation_headers import postgres_statements

SESSION_OBSERVATION_HEADERS_MIGRATION = Migration(
    version=69,
    name="bounded_session_observation_headers",
    statements=postgres_statements(),
)
