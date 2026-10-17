"""v103: reuse plans inside the two bounded source projection functions."""

from agent_storage.postgres.migration_types import Migration

TASK_PROJECTION_TRIGGER_PLAN_MIGRATION = Migration(
    version=103,
    name="function_scoped_projection_plan_reuse",
    # ponytail: retain every native query/guard; PG restores the caller's setting.
    # First use still plans, and schema/statistics changes can invalidate cached plans.
    statements=(
        "ALTER FUNCTION route_task_projection_work() "
        "SET plan_cache_mode TO force_generic_plan",
        "ALTER FUNCTION write_projection_source_metadata(text,uuid) "
        "SET plan_cache_mode TO force_generic_plan",
    ),
)
