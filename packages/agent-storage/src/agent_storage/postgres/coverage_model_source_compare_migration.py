"""v127: compare coverage sources by columns, not whole-row JSONB serialization.

CA-HA-03 D2: the v96 UPDATE triggers gated `advance_coverage_model_*` with
`coverage_model_event_source(to_jsonb(OLD)) IS DISTINCT FROM ...(to_jsonb(NEW))`,
serializing both row images per updated event. Derived-state writes (position
allocation, projection blocks) update event rows heavily; at 1 task/s the
comparison executed ~466 times/s with equal operands. A column-wise
IS DISTINCT ROW compare is semantically identical and skips serialization.
"""

from agent_storage.postgres.migration_types import Migration

# session_events columns minus the v96-excluded derived coordinates
# (task_id, task_sequence, projection_block_start).
_SOURCE_COLUMNS = (
    "deployment_namespace",
    "event_id",
    "session_id",
    "sequence",
    "event_type",
    "payload",
    "actor",
    "created_at",
    "causation_id",
    "correlation_id",
    "idempotency_key",
    "policy_version",
    "model_profile",
    "event_bytes_bound_v1",
    "event_bytes_bound",
    "replay_command_kind",
    "replay_run_id",
    "replay_internal_continuation",
    "replay_header_ready",
    "projection_handoff_id",
    "projection_peer_segment_id",
    "projection_metadata_ready",
)
_OLD_ROW = ", ".join(f"OLD.{name}" for name in _SOURCE_COLUMNS)
_NEW_ROW = ", ".join(f"NEW.{name}" for name in _SOURCE_COLUMNS)

COVERAGE_MODEL_SOURCE_COMPARE_MIGRATION = Migration(
    version=127,
    name="coverage_model_source_compare",
    statements=tuple(
        f"""DROP TRIGGER coverage_model_{kind}_source_update ON session_events"""
        for kind in ("summary", "revision")
    )
    + tuple(
        f"""CREATE TRIGGER coverage_model_{kind}_source_update
           AFTER UPDATE ON session_events FOR EACH ROW
           WHEN (({_OLD_ROW}) IS DISTINCT FROM ({_NEW_ROW}))
           EXECUTE FUNCTION advance_coverage_model_{kind}()"""
        for kind in ("summary", "revision")
    ),
)
