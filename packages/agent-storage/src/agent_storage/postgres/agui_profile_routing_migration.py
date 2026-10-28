"""v115: isolate source privacy routing for explicitly bound AG-UI profiles."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.projection_work_classification_migration import _CLASSIFIED_SOURCE
from agent_storage.postgres.projection_work_migration import _SOURCE, _TASK_SOURCE
from agent_storage.projection_work_routing import (
    activate_privacy,
    classified_pending,
    classified_source,
    routed_statements,
)

AGUI_PROFILE_ROUTING_MIGRATION = Migration(
    version=115,
    name="agui_profile_projection_routing",
    statements=(
        "CREATE OR REPLACE FUNCTION wake_projection_work_task() RETURNS trigger AS $$ BEGIN "
        "PERFORM pg_advisory_xact_lock(68,hashtext(NEW.deployment_namespace)); "
        + classified_pending(_TASK_SOURCE, postgres=True, profiles=True)
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql VOLATILE",
        "CREATE OR REPLACE FUNCTION route_task_projection_work() RETURNS trigger AS $$ "
        "DECLARE source_versions TEXT[]; source_privacy BIGINT; BEGIN "
        "IF NEW.task_id IS NULL OR NEW.task_sequence IS NULL THEN RETURN NEW; END IF; "
        "IF NOT NEW.replay_header_ready THEN "
        + classified_pending(_SOURCE, postgres=True, profiles=True)
        + ";"
        + activate_privacy(_SOURCE, postgres=True, profiles=True)
        + "; RETURN NEW; END IF; "
        # ponytail: one source-trigger invocation owns these bounded scalar values;
        # no cross-event cache. Existing routing still checks each version's enabled flag.
        "SELECT array_agg(s.routed_version),max(s.privacy_frontier) "
        "INTO source_versions,source_privacy FROM ("
        + classified_source(_SOURCE, postgres=True, profiles=True)
        + ") s; "
        "IF source_versions IS NULL THEN RETURN NEW; END IF; "
        + ";".join(
            routed_statements(
                _CLASSIFIED_SOURCE,
                postgres=True,
                preclassified=True,
                profiles=True,
            )
        )
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql",
        "ALTER FUNCTION route_task_projection_work() SET plan_cache_mode TO force_generic_plan",
        "UPDATE task_projection_work_projectors SET "
        "bootstrap_after_task_id=NULL,bootstrap_complete=0 "
        "WHERE projector_version LIKE 'agui-standard-1.0:r%' "
        "OR projector_version LIKE 'zebra-reliable-v2-agui-1.0:r%'",
    ),
)
