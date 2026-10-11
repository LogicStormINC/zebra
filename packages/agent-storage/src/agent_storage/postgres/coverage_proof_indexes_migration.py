"""v94: bounded materialization proof by deployment and exact Artifact URI."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_PROOF_INDEXES_MIGRATION = Migration(
    version=94,
    name="coverage_materialization_proof_lookup",
    statements=(
        """CREATE INDEX coverage_artifact_materialized_uri ON session_events
           (deployment_namespace,((payload->'metadata'->>'artifact_uri')))
           WHERE event_type='coverage_artifact_materialized'""",
    ),
)
