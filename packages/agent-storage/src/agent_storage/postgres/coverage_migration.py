"""v78: rebuildable coverage indexes and dormant continuation intent."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_MIGRATION = Migration(
    version=78,
    name="coverage_persistence",
    statements=(
        """CREATE TABLE coverage_runs (
            deployment_namespace TEXT NOT NULL,
            namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            session_id UUID NOT NULL,
            task_id UUID NOT NULL,
            binding JSONB NOT NULL,
            source_watermark BIGINT NOT NULL CHECK (source_watermark >= 1),
            cancelled BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (deployment_namespace, namespace, run_id)
        )""",
        """CREATE TABLE coverage_units (
            deployment_namespace TEXT NOT NULL,
            namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            unit_digest TEXT NOT NULL,
            ordinal BIGINT NOT NULL CHECK (ordinal >= 0),
            unit_key JSONB NOT NULL,
            result JSONB,
            PRIMARY KEY (deployment_namespace, namespace, run_id, unit_digest),
            UNIQUE (deployment_namespace, namespace, run_id, ordinal),
            FOREIGN KEY (deployment_namespace, namespace, run_id)
                REFERENCES coverage_runs ON DELETE CASCADE
        )""",
        """CREATE INDEX coverage_units_missing ON coverage_units
            (deployment_namespace, namespace, run_id, ordinal) WHERE result IS NULL""",
        """CREATE TABLE coverage_batches (
            deployment_namespace TEXT NOT NULL,
            namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            commit_key TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            receipt JSONB NOT NULL,
            event_id UUID NOT NULL,
            PRIMARY KEY (deployment_namespace, namespace, run_id, commit_key),
            FOREIGN KEY (deployment_namespace, namespace, run_id)
                REFERENCES coverage_runs ON DELETE CASCADE,
            FOREIGN KEY (deployment_namespace, event_id) REFERENCES session_events
        )""",
        """CREATE TABLE coverage_continuations (
            deployment_namespace TEXT NOT NULL,
            namespace TEXT NOT NULL,
            run_id TEXT NOT NULL,
            source_watermark BIGINT NOT NULL,
            PRIMARY KEY (deployment_namespace, namespace, run_id),
            FOREIGN KEY (deployment_namespace, namespace, run_id)
                REFERENCES coverage_runs ON DELETE CASCADE
        )""",
        """CREATE INDEX coverage_event_history ON session_events
            (deployment_namespace, (payload->>'namespace'), (payload->>'run_id'), sequence)
            WHERE event_type IN ('coverage_manifest_committed', 'coverage_batch_accepted',
                                 'coverage_run_cancelled')""",
    ),
)
