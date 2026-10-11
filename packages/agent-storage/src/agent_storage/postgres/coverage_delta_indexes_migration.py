"""v92: exact tenant/run delta lookups; no proof or authority shortcuts."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_DELTA_INDEXES_MIGRATION = Migration(
    version=92,
    name="coverage_delta_lookup_indexes",
    statements=(
        """CREATE INDEX coverage_model_settled_unit ON coverage_model_calls
           (deployment_namespace,namespace,run_id,((reservation->'key')))
           WHERE receipt IS NOT NULL""",
        """CREATE INDEX coverage_model_record_calls ON coverage_model_calls
           (deployment_namespace,namespace,run_id,
             ((reservation #>> '{key,record_id}')),reservation_key)""",
        """CREATE INDEX coverage_model_reserved_key ON session_events
           (deployment_namespace,session_id,((payload->>'namespace')),
             ((payload->>'run_id')),((payload->'reservation'->>'reservation_key')))
           WHERE event_type='coverage_model_call_reserved'""",
    ),
)
