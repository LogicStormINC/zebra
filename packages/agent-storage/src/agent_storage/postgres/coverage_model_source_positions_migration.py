"""v96: Task position allocation is derived state, not a MODEL source mutation."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_MODEL_SOURCE_POSITIONS_MIGRATION = Migration(
    version=96,
    name="coverage_model_source_positions",
    statements=(
        # Only these late-allocated fields are excluded. Native Task guards still
        # enforce their ownership/immutability; every business/source field stays.
        """CREATE FUNCTION coverage_model_event_source(body JSONB) RETURNS JSONB
           LANGUAGE sql IMMUTABLE STRICT AS $$
             SELECT body - ARRAY['task_id','task_sequence','projection_block_start']::text[]
           $$""",
        *tuple(
            statement
            for kind in ("summary", "revision")
            for statement in (
                f"DROP TRIGGER coverage_model_{kind}_session_events ON session_events",
                f"""CREATE TRIGGER coverage_model_{kind}_session_events
                   AFTER INSERT OR DELETE ON session_events FOR EACH ROW
                   EXECUTE FUNCTION advance_coverage_model_{kind}()""",
                f"""CREATE TRIGGER coverage_model_{kind}_source_update
                   AFTER UPDATE ON session_events FOR EACH ROW
                   WHEN (coverage_model_event_source(to_jsonb(OLD)) IS DISTINCT FROM
                         coverage_model_event_source(to_jsonb(NEW)))
                   EXECUTE FUNCTION advance_coverage_model_{kind}()""",
            )
        ),
        # Keep v91's whole-row volume accounting exact after derived allocation.
        # Never restore an invalidated legacy summary or grant it fresh authority.
        """CREATE FUNCTION advance_coverage_model_position_volume() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF NEW.event_type IN ('coverage_model_budget_initialized',
               'coverage_model_call_reserved','coverage_model_usage_recorded') THEN
               UPDATE coverage_model_summary SET source_bytes=source_bytes
                 +octet_length(to_jsonb(NEW)::text)-octet_length(to_jsonb(OLD)::text)
                 WHERE deployment_namespace=NEW.deployment_namespace
                   AND namespace=NEW.payload->>'namespace' AND run_id=NEW.payload->>'run_id'
                   AND volume_ready AND NOT invalidated;
             END IF;
             RETURN NULL;
           END $$""",
        """CREATE TRIGGER coverage_model_position_volume AFTER UPDATE ON session_events
           FOR EACH ROW WHEN (to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW)
             AND coverage_model_event_source(to_jsonb(OLD)) IS NOT DISTINCT FROM
                 coverage_model_event_source(to_jsonb(NEW)))
           EXECUTE FUNCTION advance_coverage_model_position_volume()""",
    ),
)
