"""v100: correlate scalar route updates across explicitly enabled projectors."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.projection_work_migration import _SOURCE
from agent_storage.projection_work_routing import (
    activate_privacy,
    classified_pending,
    routed_statements,
)

TASK_PROJECTION_WORK_FANOUT_MIGRATION = Migration(
    version=100,
    name="projector_scoped_scalar_fanout",
    statements=(
        "CREATE OR REPLACE FUNCTION route_task_projection_work() RETURNS trigger AS $$ BEGIN "
        "IF NEW.task_id IS NULL OR NEW.task_sequence IS NULL THEN RETURN NEW; END IF; "
        "IF NOT NEW.replay_header_ready THEN "
        + classified_pending(_SOURCE, postgres=True)
        + ";"
        + activate_privacy(_SOURCE, postgres=True)
        + "; RETURN NEW; END IF; "
        + ";".join(routed_statements(_SOURCE, postgres=True))
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql",
    ),
)
