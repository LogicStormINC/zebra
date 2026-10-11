"""v79: constant-time budget reservations and bounded record/result queries."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_EXECUTION_MIGRATION = Migration(
    version=79,
    name="coverage_execution_budget",
    statements=(
        """ALTER TABLE coverage_runs
           ADD COLUMN attempt_budget JSONB,
           ADD COLUMN attempt_count BIGINT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
           ADD COLUMN input_bytes_count BIGINT NOT NULL DEFAULT 0 CHECK (input_bytes_count >= 0)""",
        """DO $$ BEGIN IF EXISTS (
           SELECT 1 FROM session_events WHERE event_type='coverage_unit_attempted'
           GROUP BY deployment_namespace,payload->>'namespace',payload->>'run_id'
           HAVING count(DISTINCT payload->'budget')<>1)
           THEN RAISE EXCEPTION 'conflicting coverage budget Events'; END IF; END $$""",
        """UPDATE coverage_runs run SET attempt_budget=usage.budget,
           attempt_count=usage.attempts,input_bytes_count=usage.bytes
           FROM (SELECT deployment_namespace,payload->>'namespace' AS namespace,
           payload->>'run_id' AS run_id,(jsonb_agg(DISTINCT payload->'budget'))->0 AS budget,
           count(*) AS attempts,sum((payload->>'input_bytes')::bigint) AS bytes
           FROM session_events WHERE event_type='coverage_unit_attempted'
           GROUP BY deployment_namespace,payload->>'namespace',payload->>'run_id') usage
           WHERE run.deployment_namespace=usage.deployment_namespace
           AND run.namespace=usage.namespace AND run.run_id=usage.run_id""",
        """CREATE INDEX coverage_accepted_record ON coverage_units
           (deployment_namespace,namespace,run_id,(unit_key->>'record_id'),ordinal)
           WHERE result IS NOT NULL""",
        """CREATE INDEX coverage_execution_events ON session_events
           (deployment_namespace,session_id,(payload->>'namespace'),(payload->>'run_id'),sequence)
           WHERE event_type IN ('coverage_unit_attempted','coverage_report_certified',
                               'coverage_artifact_materialized')""",
    ),
)
