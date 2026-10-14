"""Additive v98: exclusive source-owned AG-UI routing and late privacy repair."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.projection_work_migration import _SOURCE, _TASK_SOURCE
from agent_storage.projection_work_routing import (
    activate_privacy,
    classified_pending,
    routed_statements,
)

TASK_PROJECTION_WORK_ROUTING_MIGRATION = Migration(
    version=98,
    name="source_owned_projection_work_routing",
    statements=(
        "ALTER TABLE task_projection_work_routes ADD COLUMN privacy_frontier BIGINT "
        "NOT NULL DEFAULT -1 CHECK(privacy_frontier>=-1)",
        # Only configuration cursors, never an unbounded Task/Run adoption scan.
        "UPDATE task_projection_work_projectors SET bootstrap_after_task_id=NULL,"
        "bootstrap_complete=0",
        "CREATE OR REPLACE FUNCTION wake_projection_work_task() RETURNS trigger AS $$ BEGIN "
        "PERFORM pg_advisory_xact_lock(68,hashtext(NEW.deployment_namespace)); "
        + classified_pending(_TASK_SOURCE, postgres=True)
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql VOLATILE",
        "CREATE OR REPLACE FUNCTION route_task_projection_work() RETURNS trigger AS $$ BEGIN "
        "IF NEW.task_id IS NULL OR NEW.task_sequence IS NULL THEN RETURN NEW; END IF; "
        "IF NOT NEW.replay_header_ready THEN "
        + classified_pending(_SOURCE, postgres=True)
        + ";"
        + activate_privacy(_SOURCE, postgres=True)
        + "; RETURN NEW; END IF; "
        + ";".join(routed_statements(_SOURCE, postgres=True, legacy_scalar_source=True))
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql",
    ),
)
