"""Reuse the bounded scalar repair plans on each PostgreSQL backend."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.projection_work_routing import routed_statements

_SOURCE = """SELECT $1::text AS deployment_namespace,$2::text AS task_id,
 $3::text AS event_id,$4::bigint AS task_sequence,
 $5::text AS event_type,$6::text AS command_kind,
 $7::text AS run_id,$8::integer AS internal,$9::text AS selected_version"""

PROJECTION_WORK_REPAIR_PLAN_MIGRATION = Migration(
    version=123,
    name="projection_work_repair_plan_reuse",
    statements=(
        """CREATE FUNCTION repair_task_projection_header(
            text, text, text, bigint, text, text, text, integer, text, text
        ) RETURNS void LANGUAGE plpgsql
        SET plan_cache_mode TO force_generic_plan AS $repair$
        BEGIN
        """
        + ";".join(routed_statements(_SOURCE, postgres=True, profiles=True))
        + """;
        PERFORM set_config('statement_timeout',$10,true);
        END;
        $repair$""",
    ),
)
