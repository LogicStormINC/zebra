"""Additive v120: parent-wide budget and immutable node admission originals."""

from agent_storage.postgres.migration_types import Migration

ORCHESTRATION_ADMISSION_MIGRATION = Migration(
    version=120,
    name="orchestration_admission_originals",
    statements=(
        """CREATE TABLE orchestration_parent_budgets (
            deployment_namespace TEXT NOT NULL,
            parent_task_id UUID NOT NULL,
            binding_digest TEXT NOT NULL CHECK(length(binding_digest)=64),
            ceiling JSONB NOT NULL,
            PRIMARY KEY(deployment_namespace,parent_task_id)
        )""",
        """CREATE TABLE orchestration_admission_originals (
            deployment_namespace TEXT NOT NULL,
            original_key TEXT NOT NULL CHECK(length(original_key)=64),
            parent_task_id UUID NOT NULL,
            run_id TEXT NOT NULL,
            plan_revision BIGINT NOT NULL,
            node_key TEXT NOT NULL,
            semantic_digest TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            payload JSONB NOT NULL,
            child_task_id UUID NOT NULL,
            reservation JSONB NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('prepared','admitted')),
            receipt JSONB,
            usage JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(deployment_namespace,original_key),
            UNIQUE(deployment_namespace,run_id,plan_revision,node_key),
            UNIQUE(deployment_namespace,child_task_id),
            FOREIGN KEY(deployment_namespace,parent_task_id)
              REFERENCES orchestration_parent_budgets(deployment_namespace,parent_task_id)
        )""",
        """CREATE INDEX orchestration_admission_parent ON orchestration_admission_originals
          (deployment_namespace,parent_task_id)""",
    ),
)
