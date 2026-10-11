"""v84: append-only execution witnesses, separate from rebuildable projections."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_EXECUTION_RECEIPT_MIGRATION = Migration(
    version=84,
    name="coverage_execution_receipts",
    statements=(
        """CREATE TABLE coverage_execution_receipts (
           deployment_namespace TEXT NOT NULL, namespace TEXT NOT NULL, run_id TEXT NOT NULL,
           session_id UUID NOT NULL, event_id UUID NOT NULL, sequence BIGINT NOT NULL,
           predecessor_event_id UUID, body JSONB NOT NULL, body_digest TEXT NOT NULL,
           PRIMARY KEY (deployment_namespace,event_id),
           UNIQUE (deployment_namespace,namespace,run_id,sequence),
           FOREIGN KEY (deployment_namespace,event_id)
             REFERENCES session_events (deployment_namespace,event_id),
           FOREIGN KEY (deployment_namespace,predecessor_event_id)
             REFERENCES coverage_execution_receipts (deployment_namespace,event_id),
           CHECK (sequence>=0 AND event_id IS DISTINCT FROM predecessor_event_id),
           CHECK ((body->>'protocol') IS NOT DISTINCT FROM 'coverage-execution-receipt/1'),
           CHECK (body_digest ~ '^[0-9a-f]{64}$'))""",
        """CREATE FUNCTION reject_coverage_execution_receipt_mutation() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             RAISE EXCEPTION 'coverage execution receipts are append-only';
           END $$""",
        """CREATE TRIGGER coverage_execution_receipts_append_only
           BEFORE UPDATE OR DELETE ON coverage_execution_receipts
           FOR EACH ROW EXECUTE FUNCTION reject_coverage_execution_receipt_mutation()""",
        """CREATE TRIGGER coverage_execution_receipts_no_truncate
           BEFORE TRUNCATE ON coverage_execution_receipts
           FOR EACH STATEMENT EXECUTE FUNCTION reject_coverage_execution_receipt_mutation()""",
    ),
)
