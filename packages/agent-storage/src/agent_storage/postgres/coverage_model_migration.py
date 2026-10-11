"""v80: independent witnesses survive run projection deletion/rebuild."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_MODEL_MIGRATION = Migration(
    version=80,
    name="coverage_model_budget",
    statements=(
        """CREATE TABLE coverage_model_events (
           deployment_namespace TEXT NOT NULL, namespace TEXT NOT NULL, run_id TEXT NOT NULL,
           sequence BIGINT NOT NULL, event_digest TEXT NOT NULL, source_row JSONB NOT NULL,
           PRIMARY KEY (deployment_namespace,namespace,run_id,sequence))""",
        """CREATE TABLE coverage_model_ledger (
           deployment_namespace TEXT NOT NULL, namespace TEXT NOT NULL, run_id TEXT NOT NULL,
           policy JSONB NOT NULL,
           calls BIGINT NOT NULL DEFAULT 0 CHECK (calls>=0),
           charged_tokens BIGINT NOT NULL DEFAULT 0 CHECK (charged_tokens>=0),
           unresolved BIGINT NOT NULL DEFAULT 0 CHECK (unresolved>=0),
           PRIMARY KEY (deployment_namespace,namespace,run_id))""",
        """CREATE TABLE coverage_model_calls (
           deployment_namespace TEXT NOT NULL, namespace TEXT NOT NULL, run_id TEXT NOT NULL,
           reservation_key TEXT NOT NULL, reservation JSONB NOT NULL,
           reserved_sequence BIGINT NOT NULL, receipt JSONB, receipt_sequence BIGINT,
           PRIMARY KEY (deployment_namespace,namespace,run_id,reservation_key))""",
        """CREATE INDEX coverage_model_source_events ON session_events
           (deployment_namespace,session_id,sequence)
           WHERE event_type IN ('coverage_model_budget_initialized',
             'coverage_model_call_reserved','coverage_model_usage_recorded')""",
    ),
)
