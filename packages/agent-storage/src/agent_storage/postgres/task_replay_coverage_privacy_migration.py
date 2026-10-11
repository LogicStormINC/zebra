"""v97: source-owned presence index for bounded Task-wide privacy reads."""

from agent_storage.postgres.migration_types import Migration

# Match the public projector's presence rule, not admission validity. Null or
# malformed historical admissions must still suppress every private prefix.
COVERAGE_PRIVACY = """((event_type='task_prepared' AND payload ? 'coverage_admission')
    OR event_type IN ('coverage_manifest_committed','coverage_batch_accepted',
                     'coverage_run_cancelled','coverage_report_certified'))"""

TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION = Migration(
    version=97,
    name="task_replay_coverage_privacy",
    statements=(
        # Do not inline the body predicate into hot reads. Its conservative TOAST
        # cost also keeps fresh zero-row statistics from choosing a history filter
        # over the covering presence index. Only source writes/index build evaluate it.
        "CREATE FUNCTION task_replay_coverage_marker(p_event_type text,p_payload jsonb) "
        "RETURNS boolean LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE COST 1000 AS $$ "
        "BEGIN RETURN "
        + COVERAGE_PRIVACY.replace("event_type", "p_event_type").replace("payload", "p_payload")
        + "; END; $$",
        "CREATE INDEX session_events_coverage_privacy ON session_events "
        "(deployment_namespace,task_id,task_sequence) "
        "WHERE task_id IS NOT NULL AND task_replay_coverage_marker(event_type,payload)",
        # A view exposes only source coordinates to metadata-only database roles.
        # No stored column: historic MODEL row witnesses and byte roots stay exact.
        "CREATE VIEW task_replay_coverage_privacy AS "
        "SELECT deployment_namespace,task_id,task_sequence FROM session_events "
        "WHERE task_id IS NOT NULL AND task_replay_coverage_marker(event_type,payload)",
    ),
)
