"""v102: classify one canonical source once, preserving set-based projector fanout."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.projection_work_migration import _SOURCE
from agent_storage.projection_work_routing import (
    activate_privacy,
    classified_pending,
    classified_source,
    routed_statements,
)

_CLASSIFIED_SOURCE = _SOURCE.replace(
    "NULL::text AS selected_version",
    "versions.projector_version AS selected_version,"
    "versions.projector_version AS routed_version,source_privacy AS privacy_frontier",
) + (
    " FROM unnest(source_versions) AS versions(projector_version) WHERE EXISTS ("
    "SELECT 1 FROM task_projection_work_projectors enabled "
    "WHERE enabled.deployment_namespace=NEW.deployment_namespace "
    "AND enabled.projector_version=versions.projector_version AND enabled.enabled=1)"
)

TASK_PROJECTION_WORK_CLASSIFICATION_MIGRATION = Migration(
    version=102,
    name="source_once_projection_work_classification",
    statements=(
        "CREATE OR REPLACE FUNCTION route_task_projection_work() RETURNS trigger AS $$ "
        "DECLARE source_versions TEXT[]; source_privacy BIGINT; BEGIN "
        "IF NEW.task_id IS NULL OR NEW.task_sequence IS NULL THEN RETURN NEW; END IF; "
        "IF NOT NEW.replay_header_ready THEN "
        + classified_pending(_SOURCE, postgres=True) + ";"
        + activate_privacy(_SOURCE, postgres=True) + "; RETURN NEW; END IF; "
        # ponytail: one source-trigger invocation owns these bounded scalar values;
        # no cross-event cache. Existing routing still checks each version's enabled flag.
        "SELECT array_agg(s.routed_version),max(s.privacy_frontier) "
        "INTO source_versions,source_privacy FROM ("
        + classified_source(_SOURCE, postgres=True) + ") s; "
        "IF source_versions IS NULL THEN RETURN NEW; END IF; "
        + ";".join(routed_statements(
            _CLASSIFIED_SOURCE, postgres=True, preclassified=True,
        ))
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql",
    ),
)
