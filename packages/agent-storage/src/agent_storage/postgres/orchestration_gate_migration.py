"""v122: immutable exact-scope completion observations (not legacy v27 receipts)."""

from agent_storage.postgres.migration_types import Migration

ORCHESTRATION_GATE_MIGRATION = Migration(
    version=122,
    name="orchestration_completion_observations",
    statements=(
        """CREATE TABLE orchestration_completion_observations (
          deployment_namespace TEXT NOT NULL, run_id TEXT NOT NULL,
          plan_revision BIGINT NOT NULL CHECK(plan_revision>0),
          input_digest TEXT NOT NULL CHECK(input_digest ~ '^[0-9a-f]{64}$'),
          facts JSONB NOT NULL, evaluation JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          PRIMARY KEY(deployment_namespace,run_id,plan_revision,input_digest),
          FOREIGN KEY(deployment_namespace,run_id,plan_revision)
            REFERENCES orchestration_plan_revisions(deployment_namespace,run_id,plan_revision)
        )""",
        """CREATE FUNCTION immutable_orchestration_completion_observation() RETURNS trigger
          LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'completion observations are immutable';
          END $$""",
        """CREATE TRIGGER immutable_orchestration_completion_observation
          BEFORE UPDATE OR DELETE ON orchestration_completion_observations
          FOR EACH ROW EXECUTE FUNCTION immutable_orchestration_completion_observation()""",
    ),
)
