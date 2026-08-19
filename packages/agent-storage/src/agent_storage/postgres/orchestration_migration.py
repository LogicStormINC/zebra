"""PostgreSQL v27: orchestration control-plane projections (plan 13.1)."""

from agent_storage.postgres.migration_types import Migration

ORCHESTRATION_MIGRATION = Migration(
    version=27,
    name="orchestration_projections",
    statements=(
        """
        CREATE TABLE orchestration_runs (
            deployment_namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            parent_task_id UUID NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'proposed', 'validated', 'materializing', 'running', 'waiting',
                'synthesizing', 'completed', 'failed', 'cancelled',
                'suspended', 'blocked', 'uncertain'
            )),
            current_plan_revision BIGINT NOT NULL CHECK (current_plan_revision >= 1),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, run_id)
        )
        """,
        """
        CREATE TABLE orchestration_plan_revisions (
            deployment_namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            plan_revision BIGINT NOT NULL CHECK (plan_revision >= 1),
            plan_digest TEXT NOT NULL,
            snapshot_json JSONB NOT NULL,
            validated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, run_id, plan_revision)
        )
        """,
        """
        CREATE TABLE orchestration_nodes (
            deployment_namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            plan_revision BIGINT NOT NULL,
            node_key TEXT NOT NULL,
            child_task_id UUID,
            status TEXT NOT NULL DEFAULT 'blocked' CHECK (status IN (
                'blocked', 'ready', 'queued', 'running', 'waiting_approval',
                'waiting_children', 'verifying', 'completed', 'failed',
                'cancelled', 'skipped', 'uncertain'
            )),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, run_id, plan_revision, node_key)
        )
        """,
        """
        CREATE TABLE orchestration_dependencies (
            deployment_namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            plan_revision BIGINT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            PRIMARY KEY (deployment_namespace, run_id, plan_revision, from_node, to_node)
        )
        """,
        """
        CREATE TABLE orchestration_result_bundles (
            deployment_namespace TEXT NOT NULL,
            child_task_id UUID NOT NULL,
            result_digest TEXT NOT NULL,
            summary TEXT NOT NULL,
            artifact_refs JSONB NOT NULL,
            evidence_index JSONB NOT NULL,
            gate_receipt_id TEXT,
            published_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, child_task_id)
        )
        """,
        """
        CREATE TABLE completion_gate_receipts (
            deployment_namespace TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            child_task_id UUID NOT NULL,
            gate_name TEXT NOT NULL,
            passed BOOLEAN NOT NULL,
            reason_code TEXT NOT NULL,
            evaluated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, receipt_id)
        )
        """,
        """
        CREATE INDEX orchestration_runs_parent
        ON orchestration_runs (deployment_namespace, parent_task_id)
        """,
        """
        CREATE INDEX orchestration_nodes_children
        ON orchestration_nodes (deployment_namespace, child_task_id)
        """,
    ),
)
