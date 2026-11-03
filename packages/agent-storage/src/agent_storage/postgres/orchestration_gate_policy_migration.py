"""v123: exact-revision immutable trusted completion policy freeze."""

from agent_storage.postgres.migration_types import Migration

ORCHESTRATION_GATE_POLICY_MIGRATION = Migration(
    version=123,
    name="orchestration_completion_policy",
    statements=(
        """CREATE TABLE orchestration_completion_policies (
          deployment_namespace TEXT NOT NULL, run_id TEXT NOT NULL,
          plan_revision BIGINT NOT NULL, policy JSONB NOT NULL,
          PRIMARY KEY(deployment_namespace,run_id,plan_revision),
          FOREIGN KEY(deployment_namespace,run_id,plan_revision)
            REFERENCES orchestration_plan_revisions(deployment_namespace,run_id,plan_revision)
        )""",
        """CREATE TRIGGER immutable_orchestration_completion_policy
          BEFORE UPDATE OR DELETE ON orchestration_completion_policies
          FOR EACH ROW EXECUTE FUNCTION immutable_orchestration_completion_observation()""",
    ),
)
